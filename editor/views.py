import uuid
from django.shortcuts import render
from django.http import JsonResponse
from django.views.decorators.csrf import csrf_exempt
from django.core.files.storage import FileSystemStorage
from django.utils.text import get_valid_filename
import fitz  # PyMuPDF
import os
from django.conf import settings
import json
from dotenv import load_dotenv

try:
    from google import genai
    from google.genai import types
except ImportError:
    genai = None

load_dotenv()

MAX_PDF_SIZE = 25 * 1024 * 1024
MAX_IMAGE_SIZE = 10 * 1024 * 1024
ALLOWED_IMAGE_EXTENSIONS = {'.png', '.jpg', '.jpeg', '.webp'}

FONT_FILES = {
    'Arial': os.path.join(settings.MEDIA_ROOT, 'fonts', 'Arial.ttf'),
    'Times New Roman': os.path.join(settings.MEDIA_ROOT, 'fonts', 'TimesNewRoman.ttf'),
    'Courier New': os.path.join(settings.MEDIA_ROOT, 'fonts', 'CourierNew.ttf'),
    'Verdana': os.path.join(settings.MEDIA_ROOT, 'fonts', 'Verdana.ttf'),
    'Tahoma': os.path.join(settings.MEDIA_ROOT, 'fonts', 'Tahoma.ttf'),
    'Roboto': os.path.join(settings.MEDIA_ROOT, 'fonts', 'Roboto-Regular.ttf'),
    'Open Sans': os.path.join(settings.MEDIA_ROOT, 'fonts', 'OpenSans-Regular.ttf'),
}

# PyMuPDF built-in fonts (no file needed)
BUILTIN_FONTS = {
    'Helvetica': 'helv',
    'Times-Roman': 'tiro',
    'Courier': 'cour',
}


def media_path_from_url(file_path):
    relative_path = (file_path or '').replace(settings.MEDIA_URL, '', 1).lstrip('/')
    full_path = os.path.abspath(os.path.join(settings.MEDIA_ROOT, relative_path))
    media_root = os.path.abspath(settings.MEDIA_ROOT)
    if not full_path.startswith(media_root + os.sep):
        raise ValueError('Invalid media path')
    return full_path


@csrf_exempt
def upload_pdf(request):
    if request.method == 'POST':
        if 'file' not in request.FILES:
            return JsonResponse({'error': 'No file uploaded'}, status=400)
        pdf_file = request.FILES['file']
        original_name = get_valid_filename(pdf_file.name or 'document.pdf')
        if not original_name.lower().endswith('.pdf'):
            return JsonResponse({'error': 'Only PDF files are supported'}, status=400)
        if pdf_file.size > MAX_PDF_SIZE:
            return JsonResponse({'error': 'PDF must be 25 MB or smaller'}, status=400)

        upload_dir = os.path.join(settings.MEDIA_ROOT, 'pdfs')
        os.makedirs(upload_dir, exist_ok=True)
        storage = FileSystemStorage(location=upload_dir, base_url=settings.MEDIA_URL + 'pdfs/')
        file_name = storage.save(f"{uuid.uuid4().hex[:8]}_{original_name}", pdf_file)
        full_path = storage.path(file_name)

        try:
            with fitz.open(full_path) as doc:
                page_count = doc.page_count
        except Exception:
            storage.delete(file_name)
            return JsonResponse({'error': 'Uploaded file is not a valid PDF'}, status=400)

        return JsonResponse({
            'file_path': storage.url(file_name),
            'file_name': original_name,
            'page_count': page_count,
        })
    return render(request, 'editor/upload.html')


def normalize_color(color):
    if color == 'transparent':
        return None
    if not color or not isinstance(color, str) or len(color) != 7 or not color.startswith('#'):
        return (0.0, 0.0, 0.0)
    try:
        r = int(color[1:3], 16) / 255.0
        g = int(color[3:5], 16) / 255.0
        b = int(color[5:7], 16) / 255.0
        return (r, g, b)
    except ValueError:
        return (0.0, 0.0, 0.0)


def insert_text_on_page(page, x, y, text, fontsize, fontname, color):
    """Insert text using built-in or custom font, with fallback."""
    builtin = BUILTIN_FONTS.get(fontname)
    fontfile = FONT_FILES.get(fontname)
    try:
        if builtin:
            page.insert_text((x, y), text, fontsize=fontsize, fontname=builtin, color=color)
        elif fontfile and os.path.exists(fontfile):
            page.insert_text((x, y), text, fontsize=fontsize, fontfile=fontfile, fontname=fontname, color=color)
        else:
            page.insert_text((x, y), text, fontsize=fontsize, fontname='helv', color=color)
    except Exception as e:
        print(f"Font error for {fontname}: {e}, falling back to helv")
        try:
            page.insert_text((x, y), text, fontsize=fontsize, fontname='helv', color=color)
        except Exception as e2:
            print(f"Fallback also failed: {e2}")


def rect_from_edit(edit):
    x = float(edit.get('orig_x', edit.get('x', 0.0)))
    y = float(edit.get('orig_y', edit.get('y', 0.0)))
    x2 = float(edit.get('orig_x2', edit.get('x2', x + float(edit.get('width', 0.0)))))
    y2 = float(edit.get('orig_y2', edit.get('y2', y + float(edit.get('height', 0.0)))))
    if x2 <= x:
        x2 = x + float(edit.get('width', 1.0))
    if y2 <= y:
        y2 = y + float(edit.get('height', 1.0))
    return fitz.Rect(x - 1, y - 1, x2 + 1, y2 + 1)


def apply_redactions(page):
    try:
        page.apply_redactions(images=fitz.PDF_REDACT_IMAGE_PIXELS)
    except (AttributeError, TypeError):
        page.apply_redactions()


@csrf_exempt
def edit_pdf(request):
    if request.method == 'POST':
        try:
            data = json.loads(request.body)
            file_path = media_path_from_url(data['file_path'])
            doc = fitz.open(file_path)

            final_object_states = {}
            for obj_id, edit in data['edits'].items():
                edit_type = edit.get('type')
                if edit_type is None:
                    continue
                if edit_type.startswith('add_') or edit_type.startswith('edit_') or edit_type.startswith('replace_'):
                    final_object_states[obj_id] = edit
                elif edit_type.startswith('remove_'):
                    final_object_states[obj_id] = edit

            for edit in final_object_states.values():
                edit_type = edit.get('type', '')
                page_number = edit.get('page')
                if page_number is None or not (0 <= page_number < doc.page_count):
                    continue
                if edit_type in {'replace_text', 'remove_pdf_text', 'remove_pdf_image', 'replace_pdf_image'}:
                    page = doc[page_number]
                    page.add_redact_annot(rect_from_edit(edit), fill=(1, 1, 1))

            for page in doc:
                redactions = list(page.annots(types=(fitz.PDF_ANNOT_REDACT,)) or [])
                if redactions:
                    apply_redactions(page)

            for obj_id, edit in final_object_states.items():
                edit_type = edit.get('type')
                page_number = edit.get('page')

                if page_number is None or not (0 <= page_number < doc.page_count):
                    continue

                page = doc[page_number]

                if edit_type in {'remove_pdf_text', 'remove_pdf_image'}:
                    continue

                if edit_type.startswith('remove_'):
                    continue

                if 'replace_text' in edit_type:
                    new_text = edit.get('text', '')
                    fontsize = float(edit.get('fontsize', 12))
                    color = normalize_color(edit.get('color', '#000000'))
                    fontname = edit.get('font', 'Helvetica')

                    orig_x = float(edit.get('orig_x', edit.get('x', 0)))
                    orig_y = float(edit.get('orig_y', edit.get('y', 0)))
                    orig_x2 = float(edit.get('orig_x2', orig_x + 100))
                    orig_y2 = float(edit.get('orig_y2', orig_y + 20))

                    baseline = orig_y2 - fontsize * 0.15
                    insert_text_on_page(page, orig_x, baseline, new_text, fontsize, fontname, color)

                elif 'text' in edit_type:
                    text = edit.get('text', edit.get('content', ''))
                    fontname = edit.get('font', 'Helvetica')
                    fontsize = float(edit.get('fontsize', 12))
                    color = normalize_color(edit.get('color', '#000000'))

                    text_x = float(edit.get('x', 0.0))
                    text_y = float(edit.get('y', 0.0))
                    text_height = float(edit.get('height', fontsize * 1.2))
                    baseline_y = text_y + text_height - (fontsize * 0.2)

                    insert_text_on_page(page, text_x, baseline_y, text, fontsize, fontname, color)

                elif 'highlight' in edit_type:
                    x = float(edit.get('x', 0.0))
                    y = float(edit.get('y', 0.0))
                    width = float(edit.get('width', 100.0))
                    height = float(edit.get('height', 20.0))
                    color = normalize_color(edit.get('color', '#FFFF00'))
                    opacity = float(edit.get('opacity', 0.4))

                    rect = fitz.Rect(x, y, x + width, y + height)
                    page.draw_rect(rect, color=None, fill=color, fill_opacity=opacity, width=0)

                elif 'rect' in edit_type:
                    x = float(edit.get('x', 0.0))
                    y = float(edit.get('y', 0.0))
                    width = float(edit.get('width', 10.0))
                    height = float(edit.get('height', 10.0))
                    color = normalize_color(edit.get('color', '#FF0000'))
                    stroke_color = normalize_color(edit.get('stroke', '#000000'))
                    stroke_width = float(edit.get('strokeWidth', 1.0))
                    opacity = float(edit.get('opacity', 1.0))

                    rect = fitz.Rect(x, y, x + width, y + height)
                    page.draw_rect(rect, color=stroke_color if stroke_width > 0 else None,
                                   fill=color, fill_opacity=opacity if color else 0, width=stroke_width)

                elif 'circle' in edit_type:
                    x = float(edit.get('x', 0.0))
                    y = float(edit.get('y', 0.0))
                    radius = float(edit.get('radius', 5.0))
                    color = normalize_color(edit.get('color', '#FF0000'))
                    stroke_color = normalize_color(edit.get('stroke', '#000000'))
                    stroke_width = float(edit.get('strokeWidth', 1.0))
                    opacity = float(edit.get('opacity', 1.0))

                    center = fitz.Point(x + radius, y + radius)
                    page.draw_circle(center, radius, color=stroke_color if stroke_width > 0 else None,
                                     fill=color, fill_opacity=opacity if color else 0, width=stroke_width)

                elif 'triangle' in edit_type:
                    x = float(edit.get('x', 0.0))
                    y = float(edit.get('y', 0.0))
                    width = float(edit.get('width', 80.0))
                    height = float(edit.get('height', 70.0))
                    color = normalize_color(edit.get('color', '#FF0000'))
                    stroke_color = normalize_color(edit.get('stroke', '#000000'))
                    stroke_width = float(edit.get('strokeWidth', 1.0))
                    opacity = float(edit.get('opacity', 1.0))

                    p1 = fitz.Point(x + width / 2, y)
                    p2 = fitz.Point(x, y + height)
                    p3 = fitz.Point(x + width, y + height)
                    page.draw_polygon([p1, p2, p3], color=stroke_color if stroke_width > 0 else None,
                                      fill=color, fill_opacity=opacity if color else 0, width=stroke_width)

                elif 'arrow' in edit_type:
                    x1 = float(edit.get('x1', 0.0))
                    y1 = float(edit.get('y1', 0.0))
                    x2 = float(edit.get('x2', 100.0))
                    y2 = float(edit.get('y2', 0.0))
                    color = normalize_color(edit.get('color', '#000000'))
                    stroke_width = float(edit.get('strokeWidth', 2.0))

                    import math
                    page.draw_line(fitz.Point(x1, y1), fitz.Point(x2, y2), color=color, width=stroke_width)
                    angle = math.atan2(y2 - y1, x2 - x1)
                    head_size = max(10, stroke_width * 4)
                    a1 = fitz.Point(x2 - head_size * math.cos(angle - math.pi / 6),
                                    y2 - head_size * math.sin(angle - math.pi / 6))
                    a2 = fitz.Point(x2 - head_size * math.cos(angle + math.pi / 6),
                                    y2 - head_size * math.sin(angle + math.pi / 6))
                    page.draw_polygon([fitz.Point(x2, y2), a1, a2], color=color, fill=color, width=0)

                elif 'line' in edit_type:
                    x1 = float(edit.get('x1', 0.0))
                    y1 = float(edit.get('y1', 0.0))
                    x2 = float(edit.get('x2', 10.0))
                    y2 = float(edit.get('y2', 10.0))
                    color = normalize_color(edit.get('color', '#000000'))
                    stroke_width = float(edit.get('strokeWidth', 1.0))

                    page.draw_line(fitz.Point(x1, y1), fitz.Point(x2, y2), color=color, width=stroke_width)

                elif 'freehand' in edit_type:
                    path_data = edit.get('path', [])
                    color = normalize_color(edit.get('color', '#000000'))
                    stroke_width = float(edit.get('strokeWidth', 2.0))

                    if len(path_data) >= 2:
                        points = [fitz.Point(float(p[0]), float(p[1])) for p in path_data]
                        for i in range(len(points) - 1):
                            page.draw_line(points[i], points[i + 1], color=color, width=stroke_width)

                elif 'image' in edit_type:
                    image_url = edit.get('image_path')
                    x = float(edit.get('x', 0.0))
                    y = float(edit.get('y', 0.0))
                    width = float(edit.get('width', 50.0))
                    height = float(edit.get('height', 50.0))

                    if not image_url:
                        continue

                    image_filename = os.path.basename(image_url.split('?')[0])
                    image_path_on_disk = os.path.join(settings.MEDIA_ROOT, 'images', image_filename)

                    if os.path.exists(image_path_on_disk):
                        rect = fitz.Rect(x, y, x + width, y + height)
                        page.insert_image(rect, filename=image_path_on_disk)

            unique_id = uuid.uuid4().hex[:8]
            original_filename_base = os.path.splitext(os.path.basename(file_path))[0]
            new_file_name = f"{original_filename_base}_edited_{unique_id}.pdf"
            new_file_path_full = os.path.join(settings.MEDIA_ROOT, 'pdfs', new_file_name)
            os.makedirs(os.path.dirname(new_file_path_full), exist_ok=True)

            doc.save(new_file_path_full)
            output_url = settings.MEDIA_URL + 'pdfs/' + new_file_name
            return JsonResponse({'status': 'success', 'new_file_path': output_url})

        except Exception as e:
            print(f"Error in edit_pdf: {e}")
            import traceback
            traceback.print_exc()
            return JsonResponse({'status': 'failed', 'error': str(e)}, status=500)

    return JsonResponse({'status': 'failed', 'error': 'Invalid request method'}, status=400)


@csrf_exempt
def upload_image(request):
    if request.method == 'POST':
        if 'file' not in request.FILES:
            return JsonResponse({'error': 'No file uploaded'}, status=400)
        image_file = request.FILES['file']
        original_filename = get_valid_filename(os.path.splitext(image_file.name)[0] or 'image')
        file_extension = os.path.splitext(image_file.name)[1].lower()
        if file_extension not in ALLOWED_IMAGE_EXTENSIONS:
            return JsonResponse({'error': 'Only PNG, JPG, JPEG, and WEBP images are supported'}, status=400)
        if image_file.size > MAX_IMAGE_SIZE:
            return JsonResponse({'error': 'Image must be 10 MB or smaller'}, status=400)
        image_name = f"{uuid.uuid4().hex[:8]}_{original_filename}{file_extension}"

        image_dir = os.path.join(settings.MEDIA_ROOT, 'images')
        os.makedirs(image_dir, exist_ok=True)

        full_path = os.path.join(image_dir, image_name)
        with open(full_path, 'wb') as f:
            for chunk in image_file.chunks():
                f.write(chunk)

        return JsonResponse({'image_path': os.path.join(settings.MEDIA_URL, 'images', image_name)})
    return JsonResponse({'error': 'Invalid request'}, status=400)


@csrf_exempt
def extract_text_blocks(request):
    """Extract text spans with bounding boxes from a PDF page for inline editing."""
    if request.method == 'POST':
        try:
            data = json.loads(request.body)
            file_path = data.get('file_path')
            page_number = int(data.get('page', 0))

            full_file_path = media_path_from_url(file_path)
            if not os.path.exists(full_file_path):
                return JsonResponse({'status': 'failed', 'error': 'File not found'}, status=404)

            doc = fitz.open(full_file_path)
            if page_number >= doc.page_count:
                return JsonResponse({'status': 'failed', 'error': 'Invalid page'}, status=400)

            page = doc[page_number]
            blocks_data = page.get_text("dict")["blocks"]
            text_spans = []
            idx = 0

            for block in blocks_data:
                if block.get("type") == 0:
                    for line in block.get("lines", []):
                        for span in line.get("spans", []):
                            text = span.get('text', '')
                            if not text.strip():
                                continue
                            try:
                                color_int = span.get('color', 0)
                                r = (color_int >> 16) & 0xFF
                                g = (color_int >> 8) & 0xFF
                                b = color_int & 0xFF
                                color_hex = f'#{r:02x}{g:02x}{b:02x}'
                            except Exception:
                                color_hex = '#000000'

                            bbox = span['bbox']
                            text_spans.append({
                                'id': f'pdf_span_{idx}',
                                'text': text,
                                'x': round(bbox[0], 2),
                                'y': round(bbox[1], 2),
                                'x2': round(bbox[2], 2),
                                'y2': round(bbox[3], 2),
                                'width': round(bbox[2] - bbox[0], 2),
                                'height': round(bbox[3] - bbox[1], 2),
                                'fontsize': round(span.get('size', 12), 1),
                                'font': span.get('font', 'Helvetica'),
                                'color': color_hex,
                            })
                            idx += 1

            return JsonResponse({'status': 'success', 'spans': text_spans})

        except Exception as e:
            print(f"Error in extract_text_blocks: {e}")
            import traceback
            traceback.print_exc()
            return JsonResponse({'status': 'failed', 'error': str(e)}, status=500)

    return JsonResponse({'status': 'failed', 'error': 'Invalid request method'}, status=400)


@csrf_exempt
def extract_pdf_content(request):
    """Extract selectable text spans and image boxes from a PDF page."""
    if request.method == 'POST':
        try:
            data = json.loads(request.body)
            file_path = data.get('file_path')
            page_number = int(data.get('page', 0))

            full_file_path = media_path_from_url(file_path)
            if not os.path.exists(full_file_path):
                return JsonResponse({'status': 'failed', 'error': 'File not found'}, status=404)

            doc = fitz.open(full_file_path)
            if page_number < 0 or page_number >= doc.page_count:
                return JsonResponse({'status': 'failed', 'error': 'Invalid page'}, status=400)

            page = doc[page_number]
            text_spans = []
            image_boxes = []
            idx = 0

            for block in page.get_text("dict")["blocks"]:
                if block.get("type") != 0:
                    continue
                for line in block.get("lines", []):
                    for span in line.get("spans", []):
                        text = span.get('text', '')
                        if not text.strip():
                            continue
                        bbox = span['bbox']
                        color_int = span.get('color', 0)
                        r = (color_int >> 16) & 0xFF
                        g = (color_int >> 8) & 0xFF
                        b = color_int & 0xFF
                        text_spans.append({
                            'id': f'pdf_text_{page_number}_{idx}',
                            'kind': 'text',
                            'text': text,
                            'x': round(bbox[0], 2),
                            'y': round(bbox[1], 2),
                            'x2': round(bbox[2], 2),
                            'y2': round(bbox[3], 2),
                            'width': round(bbox[2] - bbox[0], 2),
                            'height': round(bbox[3] - bbox[1], 2),
                            'fontsize': round(span.get('size', 12), 1),
                            'font': span.get('font', 'Helvetica'),
                            'color': f'#{r:02x}{g:02x}{b:02x}',
                        })
                        idx += 1

            for idx, info in enumerate(page.get_image_info(xrefs=True)):
                bbox = info.get('bbox')
                if not bbox:
                    continue
                x, y, x2, y2 = bbox
                if x2 <= x or y2 <= y:
                    continue
                image_boxes.append({
                    'id': f'pdf_image_{page_number}_{idx}',
                    'kind': 'image',
                    'xref': info.get('xref'),
                    'x': round(x, 2),
                    'y': round(y, 2),
                    'x2': round(x2, 2),
                    'y2': round(y2, 2),
                    'width': round(x2 - x, 2),
                    'height': round(y2 - y, 2),
                })

            return JsonResponse({
                'status': 'success',
                'texts': text_spans,
                'images': image_boxes,
            })

        except Exception as e:
            print(f"Error in extract_pdf_content: {e}")
            import traceback
            traceback.print_exc()
            return JsonResponse({'status': 'failed', 'error': str(e)}, status=500)

    return JsonResponse({'status': 'failed', 'error': 'Invalid request method'}, status=400)


@csrf_exempt
def chat_pdf(request):
    if request.method == 'POST':
        try:
            data = json.loads(request.body)
            file_path = data.get('file_path')
            message = data.get('message')

            if not file_path or not message:
                return JsonResponse({'status': 'failed', 'error': 'Missing file path or message'}, status=400)

            full_file_path = media_path_from_url(file_path)
            if not os.path.exists(full_file_path):
                return JsonResponse({'status': 'failed', 'error': 'File not found'}, status=404)

            doc = fitz.open(full_file_path)
            pdf_text = ""
            for page in doc:
                pdf_text += page.get_text() + "\n"

            api_key = os.environ.get("GEMINI_API_KEY")
            if not api_key or genai is None:
                mock_response = (
                    f"Mock AI response to: '{message}'\n\n"
                    f"PDF contains {len(pdf_text)} characters across {doc.page_count} pages. "
                    "Set GEMINI_API_KEY in .env to enable real AI responses."
                )
                return JsonResponse({'status': 'success', 'response': mock_response})

            client = genai.Client(api_key=api_key)
            max_chars = 100000
            truncated_text = pdf_text[:max_chars]

            prompt = (
                f"You are an intelligent PDF assistant. Here is the content from a PDF document:\n\n"
                f"{truncated_text}\n\n"
                f"User question: {message}\n\n"
                f"Please provide a clear, helpful, and well-formatted response. "
                f"Use markdown formatting where appropriate (bullet points, bold text, etc.)."
            )

            response = client.models.generate_content(
                model='gemini-2.5-flash',
                contents=prompt,
            )

            return JsonResponse({'status': 'success', 'response': response.text})

        except Exception as e:
            print(f"Error in chat_pdf: {e}")
            return JsonResponse({'status': 'failed', 'error': str(e)}, status=500)

    return JsonResponse({'status': 'failed', 'error': 'Invalid request method'}, status=400)
