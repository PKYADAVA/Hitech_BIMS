from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import ValidationError
from django.db import transaction
from django.db.models import ProtectedError
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_POST

from .models import STATES_AND_TERRITORIES, ExpenseType, Hatcher, Hatchery, HatcheryExpense, Setter


def _hatchery_form_context(hatchery=None):
    return {
        "hatchery": hatchery,
        "states_and_union_territories": STATES_AND_TERRITORIES,
        "operation_types": Hatchery.OPERATION_TYPES,
    }


def _apply_posted_fields(hatchery, request):
    hatchery.hatchery_name = request.POST.get("hatchery_name", "").strip()
    hatchery.operation_type = request.POST.get("operation_type", "")
    hatchery.owner_name = request.POST.get("owner_name", "").strip()
    hatchery.contact = request.POST.get("contact", "").strip()
    hatchery.email = request.POST.get("email", "").strip()
    hatchery.state = request.POST.get("state", "")
    agreement_months = request.POST.get("agreement_months")
    hatchery.agreement_months = agreement_months or None
    if request.FILES.get("document"):
        hatchery.document = request.FILES["document"]


@login_required(login_url="login")
def hatchery_master_list(request):
    """Display a list of hatchery master records."""
    hatcheries = Hatchery.objects.all()
    return render(request, "hatchery_master_list.html", {"hatcheries": hatcheries})


@login_required(login_url="login")
def create_hatchery(request):
    """Add a new hatchery master record."""
    if request.method == "POST":
        hatchery = Hatchery()
        _apply_posted_fields(hatchery, request)
        try:
            hatchery.full_clean()
            hatchery.save()
            messages.success(request, "Hatchery added successfully.")
            return redirect("hatchery_master_list")
        except ValidationError as e:
            messages.error(request, " ".join(e.messages))

    return render(request, "hatchery_master_form.html", _hatchery_form_context())


@login_required(login_url="login")
def edit_hatchery(request, id):
    """Edit an existing hatchery master record."""
    hatchery = get_object_or_404(Hatchery, id=id)

    if hatchery.is_locked and request.method == "POST":
        messages.error(request, "This hatchery is locked and cannot be edited.")
        return redirect("hatchery_master_list")

    if request.method == "POST":
        _apply_posted_fields(hatchery, request)
        try:
            hatchery.full_clean()
            hatchery.save()
            messages.success(request, "Hatchery updated successfully.")
            return redirect("hatchery_master_list")
        except ValidationError as e:
            messages.error(request, " ".join(e.messages))

    return render(request, "hatchery_master_form.html", _hatchery_form_context(hatchery))


@login_required(login_url="login")
@require_POST
def delete_hatchery(request, id):
    """Delete a hatchery master record."""
    hatchery = get_object_or_404(Hatchery, id=id)
    if hatchery.is_locked:
        messages.error(request, "This hatchery is locked and cannot be deleted.")
    else:
        hatchery.delete()
        messages.success(request, "Hatchery deleted successfully.")
    return redirect("hatchery_master_list")


@login_required(login_url="login")
@require_POST
def toggle_hatchery_active(request, id):
    """Toggle a hatchery's active/inactive status."""
    hatchery = get_object_or_404(Hatchery, id=id)
    if hatchery.is_locked:
        messages.error(request, "This hatchery is locked.")
    else:
        hatchery.is_active = not hatchery.is_active
        hatchery.save(update_fields=["is_active"])
        messages.success(request, f"Hatchery {'activated' if hatchery.is_active else 'paused'}.")
    return redirect("hatchery_master_list")


@login_required(login_url="login")
@require_POST
def toggle_hatchery_lock(request, id):
    """Toggle a hatchery's locked status."""
    hatchery = get_object_or_404(Hatchery, id=id)
    hatchery.is_locked = not hatchery.is_locked
    hatchery.save(update_fields=["is_locked"])
    messages.success(request, f"Hatchery {'locked' if hatchery.is_locked else 'unlocked'}.")
    return redirect("hatchery_master_list")


@login_required(login_url="login")
def setter_list(request):
    """Display a list of setter records."""
    setters = Setter.objects.select_related("hatchery").all()
    return render(request, "setter_list.html", {"setters": setters})


@login_required(login_url="login")
def create_setter(request):
    """Add one or more setter records against a single hatchery in one submit."""
    if request.method == "POST":
        hatchery_id = request.POST.get("hatchery")
        setter_nos = request.POST.getlist("setter_no[]")
        capacities = request.POST.getlist("capacity[]")

        hatchery = Hatchery.objects.filter(id=hatchery_id).first()
        if not hatchery:
            messages.error(request, "Select a valid hatchery.")
        else:
            try:
                created = 0
                with transaction.atomic():
                    for setter_no, capacity in zip(setter_nos, capacities):
                        setter_no = setter_no.strip()
                        if not setter_no or not capacity:
                            continue
                        setter = Setter(hatchery=hatchery, setter_no=setter_no, capacity=capacity)
                        setter.full_clean()
                        setter.save()
                        created += 1
                if created:
                    messages.success(request, f"{created} setter(s) added successfully.")
                    return redirect("setter_list")
                messages.error(request, "Enter at least one setter no. and capacity.")
            except ValidationError as e:
                messages.error(request, " ".join(e.messages))

    return render(request, "setter_form.html", {
        "hatcheries": Hatchery.objects.filter(is_active=True),
    })


@login_required(login_url="login")
def edit_setter(request, id):
    """Edit an existing setter record."""
    setter = get_object_or_404(Setter, id=id)

    if setter.is_locked and request.method == "POST":
        messages.error(request, "This setter is locked and cannot be edited.")
        return redirect("setter_list")

    if request.method == "POST":
        hatchery = Hatchery.objects.filter(id=request.POST.get("hatchery")).first()
        if not hatchery:
            messages.error(request, "Select a valid hatchery.")
        else:
            setter.hatchery = hatchery
            setter.setter_no = request.POST.get("setter_no", "").strip()
            setter.capacity = request.POST.get("capacity") or None
            try:
                setter.full_clean()
                setter.save()
                messages.success(request, "Setter updated successfully.")
                return redirect("setter_list")
            except ValidationError as e:
                messages.error(request, " ".join(e.messages))

    return render(request, "setter_edit_form.html", {
        "setter": setter,
        "hatcheries": Hatchery.objects.filter(is_active=True),
    })


@login_required(login_url="login")
@require_POST
def delete_setter(request, id):
    """Delete a setter record."""
    setter = get_object_or_404(Setter, id=id)
    if setter.is_locked:
        messages.error(request, "This setter is locked and cannot be deleted.")
    else:
        setter.delete()
        messages.success(request, "Setter deleted successfully.")
    return redirect("setter_list")


@login_required(login_url="login")
@require_POST
def toggle_setter_active(request, id):
    """Toggle a setter's active/inactive status."""
    setter = get_object_or_404(Setter, id=id)
    if setter.is_locked:
        messages.error(request, "This setter is locked.")
    else:
        setter.is_active = not setter.is_active
        setter.save(update_fields=["is_active"])
        messages.success(request, f"Setter {'activated' if setter.is_active else 'paused'}.")
    return redirect("setter_list")


@login_required(login_url="login")
@require_POST
def toggle_setter_lock(request, id):
    """Toggle a setter's locked status."""
    setter = get_object_or_404(Setter, id=id)
    setter.is_locked = not setter.is_locked
    setter.save(update_fields=["is_locked"])
    messages.success(request, f"Setter {'locked' if setter.is_locked else 'unlocked'}.")
    return redirect("setter_list")


@login_required(login_url="login")
def hatcher_list(request):
    """Display a list of hatcher records."""
    hatchers = Hatcher.objects.select_related("hatchery").all()
    return render(request, "hatcher_list.html", {"hatchers": hatchers})


@login_required(login_url="login")
def create_hatcher(request):
    """Add one or more hatcher records against a single hatchery in one submit."""
    if request.method == "POST":
        hatchery_id = request.POST.get("hatchery")
        hatcher_nos = request.POST.getlist("hatcher_no[]")
        capacities = request.POST.getlist("capacity[]")

        hatchery = Hatchery.objects.filter(id=hatchery_id).first()
        if not hatchery:
            messages.error(request, "Select a valid hatchery.")
        else:
            try:
                created = 0
                with transaction.atomic():
                    for hatcher_no, capacity in zip(hatcher_nos, capacities):
                        hatcher_no = hatcher_no.strip()
                        if not hatcher_no or not capacity:
                            continue
                        hatcher = Hatcher(hatchery=hatchery, hatcher_no=hatcher_no, capacity=capacity)
                        hatcher.full_clean()
                        hatcher.save()
                        created += 1
                if created:
                    messages.success(request, f"{created} hatcher(s) added successfully.")
                    return redirect("hatcher_list")
                messages.error(request, "Enter at least one hatcher no. and capacity.")
            except ValidationError as e:
                messages.error(request, " ".join(e.messages))

    return render(request, "hatcher_form.html", {
        "hatcheries": Hatchery.objects.filter(is_active=True),
    })


@login_required(login_url="login")
def edit_hatcher(request, id):
    """Edit an existing hatcher record."""
    hatcher = get_object_or_404(Hatcher, id=id)

    if hatcher.is_locked and request.method == "POST":
        messages.error(request, "This hatcher is locked and cannot be edited.")
        return redirect("hatcher_list")

    if request.method == "POST":
        hatchery = Hatchery.objects.filter(id=request.POST.get("hatchery")).first()
        if not hatchery:
            messages.error(request, "Select a valid hatchery.")
        else:
            hatcher.hatchery = hatchery
            hatcher.hatcher_no = request.POST.get("hatcher_no", "").strip()
            hatcher.capacity = request.POST.get("capacity") or None
            try:
                hatcher.full_clean()
                hatcher.save()
                messages.success(request, "Hatcher updated successfully.")
                return redirect("hatcher_list")
            except ValidationError as e:
                messages.error(request, " ".join(e.messages))

    return render(request, "hatcher_edit_form.html", {
        "hatcher": hatcher,
        "hatcheries": Hatchery.objects.filter(is_active=True),
    })


@login_required(login_url="login")
@require_POST
def delete_hatcher(request, id):
    """Delete a hatcher record."""
    hatcher = get_object_or_404(Hatcher, id=id)
    if hatcher.is_locked:
        messages.error(request, "This hatcher is locked and cannot be deleted.")
    else:
        hatcher.delete()
        messages.success(request, "Hatcher deleted successfully.")
    return redirect("hatcher_list")


@login_required(login_url="login")
@require_POST
def toggle_hatcher_active(request, id):
    """Toggle a hatcher's active/inactive status."""
    hatcher = get_object_or_404(Hatcher, id=id)
    if hatcher.is_locked:
        messages.error(request, "This hatcher is locked.")
    else:
        hatcher.is_active = not hatcher.is_active
        hatcher.save(update_fields=["is_active"])
        messages.success(request, f"Hatcher {'activated' if hatcher.is_active else 'paused'}.")
    return redirect("hatcher_list")


@login_required(login_url="login")
@require_POST
def toggle_hatcher_lock(request, id):
    """Toggle a hatcher's locked status."""
    hatcher = get_object_or_404(Hatcher, id=id)
    hatcher.is_locked = not hatcher.is_locked
    hatcher.save(update_fields=["is_locked"])
    messages.success(request, f"Hatcher {'locked' if hatcher.is_locked else 'unlocked'}.")
    return redirect("hatcher_list")


@login_required(login_url="login")
def expense_type_list(request):
    """Display a list of expense type records."""
    expense_types = ExpenseType.objects.all()
    return render(request, "expense_type_list.html", {"expense_types": expense_types})


@login_required(login_url="login")
def create_expense_type(request):
    """Add a new expense type."""
    if request.method == "POST":
        expense_type = ExpenseType(name=request.POST.get("name", "").strip())
        try:
            expense_type.full_clean()
            expense_type.save()
            messages.success(request, "Expense type added successfully.")
            return redirect("expense_type_list")
        except ValidationError as e:
            messages.error(request, " ".join(e.messages))

    return render(request, "expense_type_form.html", {})


@login_required(login_url="login")
def edit_expense_type(request, id):
    """Edit an existing expense type."""
    expense_type = get_object_or_404(ExpenseType, id=id)

    if expense_type.is_locked and request.method == "POST":
        messages.error(request, "This expense type is locked and cannot be edited.")
        return redirect("expense_type_list")

    if request.method == "POST":
        expense_type.name = request.POST.get("name", "").strip()
        try:
            expense_type.full_clean()
            expense_type.save()
            messages.success(request, "Expense type updated successfully.")
            return redirect("expense_type_list")
        except ValidationError as e:
            messages.error(request, " ".join(e.messages))

    return render(request, "expense_type_form.html", {"expense_type": expense_type})


@login_required(login_url="login")
@require_POST
def delete_expense_type(request, id):
    """Delete an expense type."""
    expense_type = get_object_or_404(ExpenseType, id=id)
    if expense_type.is_locked:
        messages.error(request, "This expense type is locked and cannot be deleted.")
    else:
        try:
            expense_type.delete()
            messages.success(request, "Expense type deleted successfully.")
        except ProtectedError:
            messages.error(request, "This expense type has expense entries recorded against it and cannot be deleted.")
    return redirect("expense_type_list")


@login_required(login_url="login")
@require_POST
def toggle_expense_type_active(request, id):
    """Toggle an expense type's active/inactive status."""
    expense_type = get_object_or_404(ExpenseType, id=id)
    if expense_type.is_locked:
        messages.error(request, "This expense type is locked.")
    else:
        expense_type.is_active = not expense_type.is_active
        expense_type.save(update_fields=["is_active"])
        messages.success(request, f"Expense type {'activated' if expense_type.is_active else 'paused'}.")
    return redirect("expense_type_list")


@login_required(login_url="login")
@require_POST
def toggle_expense_type_lock(request, id):
    """Toggle an expense type's locked status."""
    expense_type = get_object_or_404(ExpenseType, id=id)
    expense_type.is_locked = not expense_type.is_locked
    expense_type.save(update_fields=["is_locked"])
    messages.success(request, f"Expense type {'locked' if expense_type.is_locked else 'unlocked'}.")
    return redirect("expense_type_list")


@login_required(login_url="login")
def hatchery_expense_list(request):
    """Display a list of hatchery expense line items."""
    expenses = HatcheryExpense.objects.select_related("hatchery", "expense_type").all()
    return render(request, "hatchery_expense_list.html", {"expenses": expenses})


@login_required(login_url="login")
def create_hatchery_expense(request):
    """Record expense amounts against a hatchery for a date/stage across all active expense types."""
    expense_types = ExpenseType.objects.filter(is_active=True)

    if request.method == "POST":
        date = request.POST.get("date")
        hatchery = Hatchery.objects.filter(id=request.POST.get("hatchery")).first()
        stage = request.POST.get("stage")

        if not hatchery:
            messages.error(request, "Select a valid hatchery.")
        else:
            try:
                created = 0
                with transaction.atomic():
                    for expense_type in expense_types:
                        amount = request.POST.get(f"amount_{expense_type.id}")
                        if not amount or float(amount) == 0:
                            continue
                        expense = HatcheryExpense(
                            date=date, hatchery=hatchery, stage=stage,
                            expense_type=expense_type, amount=amount,
                        )
                        expense.full_clean()
                        expense.save()
                        created += 1
                if created:
                    messages.success(request, f"{created} expense entry(ies) added successfully.")
                    return redirect("hatchery_expense_list")
                messages.error(request, "Enter at least one expense amount.")
            except ValidationError as e:
                messages.error(request, " ".join(e.messages))

    return render(request, "hatchery_expense_form.html", {
        "hatcheries": Hatchery.objects.filter(is_active=True),
        "expense_types": expense_types,
        "stage_choices": HatcheryExpense.STAGE_CHOICES,
    })


@login_required(login_url="login")
def edit_hatchery_expense(request, id):
    """Edit an existing hatchery expense line item."""
    expense = get_object_or_404(HatcheryExpense, id=id)

    if expense.is_locked and request.method == "POST":
        messages.error(request, "This expense is locked and cannot be edited.")
        return redirect("hatchery_expense_list")

    if request.method == "POST":
        hatchery = Hatchery.objects.filter(id=request.POST.get("hatchery")).first()
        expense_type = ExpenseType.objects.filter(id=request.POST.get("expense_type")).first()
        if not hatchery or not expense_type:
            messages.error(request, "Select a valid hatchery and expense type.")
        else:
            expense.date = request.POST.get("date")
            expense.hatchery = hatchery
            expense.stage = request.POST.get("stage")
            expense.expense_type = expense_type
            expense.amount = request.POST.get("amount") or None
            try:
                expense.full_clean()
                expense.save()
                messages.success(request, "Expense updated successfully.")
                return redirect("hatchery_expense_list")
            except ValidationError as e:
                messages.error(request, " ".join(e.messages))

    return render(request, "hatchery_expense_edit_form.html", {
        "expense": expense,
        "hatcheries": Hatchery.objects.filter(is_active=True),
        "expense_types": ExpenseType.objects.filter(is_active=True),
        "stage_choices": HatcheryExpense.STAGE_CHOICES,
    })


@login_required(login_url="login")
@require_POST
def delete_hatchery_expense(request, id):
    """Delete a hatchery expense line item."""
    expense = get_object_or_404(HatcheryExpense, id=id)
    if expense.is_locked:
        messages.error(request, "This expense is locked and cannot be deleted.")
    else:
        expense.delete()
        messages.success(request, "Expense deleted successfully.")
    return redirect("hatchery_expense_list")


@login_required(login_url="login")
@require_POST
def toggle_hatchery_expense_active(request, id):
    """Toggle a hatchery expense's active/inactive status."""
    expense = get_object_or_404(HatcheryExpense, id=id)
    if expense.is_locked:
        messages.error(request, "This expense is locked.")
    else:
        expense.is_active = not expense.is_active
        expense.save(update_fields=["is_active"])
        messages.success(request, f"Expense {'activated' if expense.is_active else 'paused'}.")
    return redirect("hatchery_expense_list")


@login_required(login_url="login")
@require_POST
def toggle_hatchery_expense_lock(request, id):
    """Toggle a hatchery expense's locked status."""
    expense = get_object_or_404(HatcheryExpense, id=id)
    expense.is_locked = not expense.is_locked
    expense.save(update_fields=["is_locked"])
    messages.success(request, f"Expense {'locked' if expense.is_locked else 'unlocked'}.")
    return redirect("hatchery_expense_list")
