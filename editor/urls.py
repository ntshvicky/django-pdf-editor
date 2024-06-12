from django.urls import path
from . import views

app_name = 'editor'

urlpatterns = [
    path('', views.upload_pdf, name='upload_pdf'),
    path('upload/', views.upload_pdf, name='upload_pdf'),
    path('edit/', views.edit_pdf, name='edit_pdf'),
    path('upload_image/', views.upload_image, name='upload_image'),
]
