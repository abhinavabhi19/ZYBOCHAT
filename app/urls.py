from django.urls import path
from .views import *


urlpatterns = [
    path("", login_view, name="login"),
    path("register/", register_view, name="register"),
    path("logout/", logout_view, name="logout"),
    path("users/", user_list, name="user_list"),
    path("chat/<int:user_id>/", chat_view, name="chat"),
    path("api/unread-counts/", get_unread_counts, name="unread_counts"),
]
