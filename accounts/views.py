from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth import login
from django.contrib.auth.decorators import login_required
from django.contrib.auth.models import User

from .forms import RegisterForm


def register(request):
    if request.user.is_authenticated:
        return redirect("/")

    if request.method == "POST":
        form = RegisterForm(request.POST)
        if form.is_valid():
            user = form.save()
            login(request, user)
            return redirect("/")
    else:
        form = RegisterForm()

    return render(request, "accounts/register.html", {"form": form})


@login_required
def profile(request):
    from game.models import GameResult

    recent_results = (
        GameResult.objects.filter(user=request.user)
        .select_related("room")
        .order_by("-played_at")[:10]
    )
    return render(
        request,
        "accounts/profile.html",
        {
            "profile": request.user.profile,
            "recent_results": recent_results,
        },
    )


def public_profile(request, user_id):
    from game.models import GameResult

    target_user = get_object_or_404(User, id=user_id)
    recent_results = (
        GameResult.objects.filter(user=target_user)
        .select_related("room")
        .order_by("-played_at")[:10]
    )
    return render(
        request,
        "accounts/profile.html",
        {
            "profile": target_user.profile,
            "recent_results": recent_results,
            "is_own_profile": request.user == target_user,
        },
    )
