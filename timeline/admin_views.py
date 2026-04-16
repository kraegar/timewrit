from django.shortcuts import render, redirect, get_object_or_404
from django.contrib import messages
from django.contrib.admin.views.decorators import staff_member_required
from .models import Timeline
from .gedcom_import import GedcomImporter
from django.contrib.auth.decorators import user_passes_test

def is_researcher(user):
    return user.is_superuser or user.groups.filter(name='Researchers').exists()

@user_passes_test(is_researcher)
def gedcom_import_view(request):
    timelines = Timeline.objects.filter(owner=request.user)
    if request.user.is_superuser:
        timelines = Timeline.objects.all()
    
    if request.method == 'POST' and request.FILES.get('gedcom_file'):
        gedcom_file = request.FILES['gedcom_file']
        timeline_id = request.POST.get('timeline_id')
        target_timeline = None
        if timeline_id:
            target_timeline = get_object_or_404(Timeline, pk=timeline_id)

        # Save to a temporary file for GedcomReader
        import tempfile
        import os
        with tempfile.NamedTemporaryFile(delete=False, suffix='.ged') as tmp:
            for chunk in gedcom_file.chunks():
                tmp.write(chunk)
            tmp_path = tmp.name
        
        importer = None
        try:
            importer = GedcomImporter(tmp_path, request.user, timeline=target_timeline)
            count = importer.import_all()
            messages.success(request, f"Successfully imported {count} individuals from GEDCOM.")
        except Exception as e:
            messages.error(request, f"Error importing GEDCOM: {str(e)}")
        finally:
            if importer:
                importer.close()
            if os.path.exists(tmp_path):
                os.remove(tmp_path)
        
        return redirect('admin:index')
        
    return render(request, 'admin/timeline/gedcom_import.html', {
        'title': 'GEDCOM Import',
        'opts': Timeline._meta, # For breadcrumbs/sidebar
        'timelines': timelines,
    })

@staff_member_required
def import_data(request):
    from .importers.json_importer import JsonEventImporter
    from .importers.csv_importer import EventImporter, PersonImporter, LocationImporter
    if request.method == 'POST' and request.FILES.get('csv_file'):
        uploaded_file = request.FILES['csv_file']
        import_type = request.POST.get('import_type', 'events')

        if import_type == 'json_export':
            importer = JsonEventImporter(user=request.user)
        elif import_type == 'people':
            importer = PersonImporter(user=request.user)
        elif import_type == 'locations':
            importer = LocationImporter(user=request.user)
        else:
            importer = EventImporter(user=request.user)
            
        try:
            # Check if file seems valid
            if import_type == 'json_export' and not uploaded_file.name.endswith('.json'):
                messages.error(request, 'Please upload a JSON file for the JSON Export type.')
                return redirect('import_data')
            elif import_type != 'json_export' and not uploaded_file.name.endswith('.csv'):
                messages.error(request, 'Please upload a CSV file.')
                return redirect('import_data')

            count, reports = importer.import_data(uploaded_file)
            
            # Distinguish between actual errors and the success summary report
            errors = [r for r in reports if "Imported:" not in r]
            summaries = [r for r in reports if "Imported:" in r]

            if errors:
                for err in errors[:5]:
                    messages.error(request, err)
                if len(errors) > 5:
                    messages.warning(request, f'...and {len(errors) - 5} more errors.')
            
            if summaries:
                for summary in summaries:
                    messages.success(request, summary)
            else:
                messages.success(request, f'Successfully imported {count} events.')
                
            return redirect('admin:index')
            
        except Exception as e:
            messages.error(request, f'Import failed: {str(e)}')
            
    return render(request, 'timeline/import.html')

@staff_member_required
def cloning_guide(request):
    """
    Help page for the cloning functionality in the admin.
    """
    return render(request, 'admin/cloning_guide.html')


@user_passes_test(is_researcher)
def research_board_view(request):
    """
    Centralized dashboard for managing research tasks across all entities.
    Groups questions by status and sorts by priority.
    """
    from .models import ResearchQuestion
    from django.db.models import Case, When, Value, IntegerField
    
    # 1. Handle Quick Actions (Status Updates)
    if request.method == 'POST':
        action = request.POST.get('action')
        question_id = request.POST.get('question_id')
        if action and question_id:
            question = get_object_or_404(ResearchQuestion, pk=question_id)
            # Security: Only owner or superuser can edit
            if request.user.is_superuser or question.owner == request.user:
                if action == 'resolve':
                    question.status = 'answered'
                elif action == 'defer':
                    question.status = 'deferred'
                elif action == 'reopen':
                    question.status = 'open'
                question.save()
                messages.success(request, f"Updated task status to {question.get_status_display()}")
        return redirect('research_board')

    # 2. Fetch and Optimize Data
    qs = ResearchQuestion.objects.all().prefetch_related('content_object')
    if not request.user.is_superuser:
        qs = qs.filter(owner=request.user)
    
    # Priority sorting logic (High -> Medium -> Low)
    qs = qs.annotate(
        priority_score=Case(
            When(priority='high', then=Value(0)),
            When(priority='medium', then=Value(1)),
            When(priority='low', then=Value(2)),
            default=Value(3),
            output_field=IntegerField(),
        )
    ).order_by('priority_score', '-created_at')

    # 3. Categorize and Enrich for the Kanban-style UI
    from django.urls import reverse
    
    for q in qs:
        # Generate the admin URL for the content_object manually
        if q.content_object:
            app_label = q.content_object._meta.app_label
            model_name = q.content_object._meta.model_name
            q.parent_admin_url = reverse(f'admin:{app_label}_{model_name}_change', args=[q.content_object.id])
        else:
            q.parent_admin_url = "#"

    categories = {
        'open': [q for q in qs if q.status == 'open'],
        'deferred': [q for q in qs if q.status == 'deferred'],
        'answered': [q for q in qs if q.status == 'answered'],
    }

    return render(request, 'admin/research_board.html', {
        'title': 'Research Dashboard',
        'categories': categories,
        'opts': ResearchQuestion._meta, 
    })

