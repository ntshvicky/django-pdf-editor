# AI-Powered Django PDF Editor

A premium, responsive web application for editing PDFs and chatting with your documents using AI. Built with Django, PyMuPDF, and Google's Gemini AI, featuring a modern glassmorphism user interface.

## Features

- **Modern Glassmorphism UI**: A beautiful, responsive interface that works flawlessly on desktop and mobile.
- **AI PDF Chat**: Ask questions about your PDF and get intelligent answers powered by Google's Gemini AI.
- **PDF Editing**:
  - Add text with customizable fonts, sizes, and colors.
  - Draw shapes (rectangles, circles, lines) with various styles.
  - Insert images into your PDFs.
  - Interactive canvas for precise positioning and manipulation of elements.
- **Robust File Management**: Securely upload, edit, and export your modified PDFs.

## Prerequisites

- Python 3.8+
- [Google Gemini API Key](https://aistudio.google.com/app/apikey) (for AI chat features)

## Installation

1. **Clone the repository:**
   ```bash
   git clone <repository-url>
   cd django-pdf-editor-master
   ```

2. **Create a virtual environment (recommended):**
   ```bash
   python -m venv venv
   source venv/bin/activate  # On Windows, use: venv\Scripts\activate
   ```

3. **Install dependencies:**
   ```bash
   pip install -r requirements.txt
   ```

4. **Environment Variables:**
   Create a `.env` file in the project root directory and add your Gemini API key:
   ```env
   GEMINI_API_KEY=your_gemini_api_key_here
   ```

5. **Set up the database and media directories:**
   ```bash
   python manage.py makemigrations
   python manage.py migrate
   mkdir -p media/pdfs
   mkdir -p media/fonts
   ```
   *(Note: You'll need to place your font files (.ttf) inside `media/fonts` based on the `FONT_FILES` configuration in `editor/views.py` if you wish to use custom fonts.)*

6. **Run the development server:**
   ```bash
   python manage.py runserver
   ```

7. **Access the application:**
   Open your browser and navigate to `http://127.0.0.1:8000/`.

## Deployment

This project is configured for deployment on Vercel. 
Ensure you have `whitenoise` installed and configured in `settings.py` for serving static files, and set your environment variables (like `GEMINI_API_KEY`) in your deployment platform's settings.

## Technologies Used

- **Backend**: Django, PyMuPDF, ReportLab, Google GenAI SDK
- **Frontend**: HTML5 Canvas, Vanilla CSS (Glassmorphism design), JavaScript, Markdown-IT, DOMPurify