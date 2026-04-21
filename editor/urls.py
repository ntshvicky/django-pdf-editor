from django.urls import path
from . import views

app_name = 'editor'

urlpatterns = [
    path('', views.upload_pdf, name='upload_pdf'),
    path('upload/', views.upload_pdf, name='upload_pdf_alt'),
    path('edit/', views.edit_pdf, name='edit_pdf'),
    path('upload_image/', views.upload_image, name='upload_image'),
    path('extract_text/', views.extract_text_blocks, name='extract_text_blocks'),
    path('extract_content/', views.extract_pdf_content, name='extract_pdf_content'),
    path('chat/', views.chat_pdf, name='chat_pdf'),
]
