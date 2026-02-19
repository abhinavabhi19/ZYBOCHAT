from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth import login, logout, authenticate
from django.contrib.auth.decorators import login_required
from django.contrib import messages
from django.utils import timezone
from django.http import JsonResponse
from django.db.models import Count, Q
from .models import User, Conversation, Message


def register_view(request):
    if request.method == "POST":
        username = request.POST.get("username")
        email = request.POST.get("email")
        password = request.POST.get("password")

        if User.objects.filter(email=email).exists():
            messages.error(request, "Email already exists")
            return redirect("register")

        user = User.objects.create_user(
            email=email,
            username=username,
            password=password
        )

        login(request, user)
        return redirect("user_list")

    return render(request, "register.html")



def login_view(request):
    if request.method == "POST":
        email = request.POST.get("email")
        password = request.POST.get("password")

        user = User.objects.filter(email=email).first()

        if user and user.check_password(password):
            login(request, user)
            return redirect("user_list")
        else:
            messages.error(request, "Invalid email or password")


    return render(request, "login.html")


def logout_view(request):
    logout(request)
    return redirect("login")




@login_required
def user_list(request):
    users = User.objects.exclude(id=request.user.id)
    return render(request, "user_list.html", {"users": users})



@login_required
def chat_view(request, user_id):
    other_user = get_object_or_404(User, id=user_id)

    conversation, created = Conversation.objects.get_or_create(
        user1=min(request.user, other_user, key=lambda u: u.id),
        user2=max(request.user, other_user, key=lambda u: u.id),
    )

    messages = conversation.messages.all().order_by("timestamp")

    return render(request, "chat.html", {
        "other_user": other_user,
        "messages": messages
    })


@login_required
def get_unread_counts(request):
    unread_counts = {}
    
    conversations = Conversation.objects.filter(
        Q(user1=request.user) | Q(user2=request.user)
    )
    
    for conv in conversations:
        other_user = conv.user2 if conv.user1 == request.user else conv.user1
        
        unread = Message.objects.filter(
            conversation=conv,
            sender=other_user,
            is_read=False
        ).count()
        
        if unread > 0:
            unread_counts[other_user.id] = unread
    
    return JsonResponse(unread_counts)
