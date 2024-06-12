import uuid
from django.shortcuts import render
from django.http import JsonResponse
from .models import PDFDocument
import fitz  # PyMuPDF
import os
from django.conf import settings
import json

# Dictionary to map font names to file paths
FONT_FILES = {
    'Arial': os.path.join(settings.MEDIA_URL, 'fonts', 'Arial.ttf'),
    'Times New Roman': os.path.join(settings.MEDIA_URL, 'fonts', 'TimesNewRoman.ttf'),
    'Courier New': os.path.join(settings.MEDIA_URL, 'fonts', 'CourierNew.ttf'),
    'Verdana': os.path.join(settings.MEDIA_URL, 'fonts', 'Verdana.ttf'),
    'Tahoma': os.path.join(settings.MEDIA_URL, 'fonts', 'Tahoma.ttf')
}

def upload_pdf(request):
    if request.method == 'POST':
        if 'file' not in request.FILES:
            return JsonResponse({'error': 'No file uploaded'}, status=400)
        pdf_file = request.FILES['file']
        document = PDFDocument.objects.create(file=pdf_file)
        document.save()
        return JsonResponse({'file_path': document.file.url})
    return render(request, 'editor/upload.html')

def normalize_color(color):
    # Normalize the color to a tuple of (R, G, B) values 0-255 range to 0-1 range
    return tuple(c / 255.0 for c in color)

def edit_pdf(request):
    if request.method == 'POST':
        data = json.loads(request.body)
        file_path = os.path.join(settings.MEDIA_ROOT, data['file_path'].lstrip('/media/'))
        doc = fitz.open(file_path)

        # Track the final state of text and image edits
        text_edits = {}
        image_operations = {}
        shape_edits = {}

        for id, edit in data['edits'].items():
            page_number = edit['page']
            page = doc[page_number]

            if edit['type'] in ['add_text', 'edit_text', 'move_text']:
                # Use a unique identifier for each text element to track its final state
                text_id = edit.get('text_id', f"text_{edit['x']}_{edit['y']}_{page_number}")
                text_edits[text_id] = edit

            elif edit['type'] == 'remove_text':
                for text_instance in page.search_for(edit['text']):
                    page.insert_text(text_instance.rect.tl, "")

            elif edit['type'] in ['add_image', 'move_image']:
                image_url = edit['image_path'] if edit['type'] == 'add_image' else edit['content']
                image_operations[image_url] = (page_number, edit['x'], edit['y'], edit['x']+edit['width'], edit['y']+edit['height'])

            elif edit['type'] in ['add_rect', 'add_circle', 'move_rect', 'move_circle', ]:
                shape_id = edit.get('shape_id', f"shape_{edit['x']}_{edit['y']}_{page_number}")
                shape_edits[shape_id] = edit
            elif edit['type'] in ['add_line', 'move_line']:
                shape_id = edit.get('shape_id', f"shape_{edit['x1']}_{edit['y1']}_{page_number}")
                shape_edits[shape_id] = edit

        # Apply the final state of text edits
        for text_id, edit in text_edits.items():
            color = (0, 0, 0) if 'color' not in edit else normalize_color(tuple(int(edit['color'][i:i+2], 16) for i in (1, 3, 5)))
            page = doc[edit['page']]
            text = edit.get('text', edit.get('content', ''))
            fontname = edit.get('font', 'Arial')
            fontsize = edit.get('fontsize', 12) - 2 #-2 added bcz size was not working as view
            fontstyle = edit.get('fontstyle', 'normal')

            # Correct text position
            text_x = edit['x'] + 10.0 #_10 added bcz x-axis was not working as view
            text_y = edit['y'] + edit['height'] if edit['type']=='move_text' else  edit['y']
            if 'move_x' in edit and 'move_y' in edit:
                text_x += edit['move_x']
                text_y += edit['move_y']

            # Use font file if specified
            fontfile = FONT_FILES.get(fontname, 'helv')
            page.insert_text((text_x, text_y), text, fontsize=fontsize, fontfile=fontfile, color=color)

        # Apply the final state of shape edits
        for shape_id, edit in shape_edits.items():
            if edit['type'] == 'remove_shape':
                continue  # Skip shapes marked for removal

            page = doc[edit['page']]
            color = (0, 0, 0) if 'color' not in edit else normalize_color(tuple(int(edit['color'][i:i+2], 16) for i in (1, 3, 5)))

            if edit['type'] == 'add_rect' or edit['type'] == 'move_rect':
                rect = fitz.Rect(edit['x'], edit['y'], edit['x'] + edit['width'], edit['y'] + edit['height'])
                page.draw_rect(rect, color=color, fill=color)

            elif edit['type'] == 'add_circle' or edit['type'] == 'move_circle':
                center = fitz.Point(edit['x']+edit['radius'], edit['y']+edit['radius'])
                page.draw_circle(center, edit['radius'], color=color, fill=color)

            elif edit['type'] == 'add_line' or edit['type'] == 'move_line':
                page.draw_line((edit['x1'], edit['y1']), (edit['x2'], edit['y2']), color=color, width=edit['strokeWidth'])


        # Apply the final operation for each image
        for image_url, (page_number, x, y, width, height) in image_operations.items():
            page = doc[page_number]
            image_filename = os.path.basename(image_url)
            image_path = os.path.join(settings.MEDIA_ROOT, 'images', image_filename)
            rect = fitz.Rect(x, y, width, height)
            page.insert_image(rect, filename=image_path)

        new_file_path = file_path.replace(".pdf", "_edited.pdf")
        doc.save(new_file_path)
        output_path = 'media' + new_file_path.replace(settings.MEDIA_ROOT, '')
        return JsonResponse({'status': 'success', 'new_file_path': output_path})
    return JsonResponse({'status': 'failed'})



def upload_image(request):
    if request.method == 'POST':
        image_file = request.FILES['file']
        image_name = uuid.uuid4().hex[:8]
        image_path = os.path.join('images', image_name)
        full_path = os.path.join(settings.MEDIA_ROOT, image_path)
        os.makedirs(os.path.dirname(full_path), exist_ok=True)
        with open(full_path, 'wb') as f:
            for chunk in image_file.chunks():
                f.write(chunk)
        return JsonResponse({'image_path': os.path.join(settings.MEDIA_URL, image_path)})
    return JsonResponse({'error': 'Invalid request'}, status=400)
