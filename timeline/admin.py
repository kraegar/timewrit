from django.contrib import admin
from django.utils.translation import gettext_lazy as _
from simple_history.admin import SimpleHistoryAdmin
from django.contrib.contenttypes.admin import GenericTabularInline
from .models import Location, LocationAlias, Person, TimelineEvent, Timeline, EventImage, PersonRelationship, Source, Tag, Attachment, Story, StoryEvent, DisputedFact, PublicComment, ResearchQuestion, HelpCategory, HelpTopic, HelpImage


@admin.register(Tag)
class TagAdmin(admin.ModelAdmin):
    list_display = ('name', 'color', 'needs_research')
    list_filter = ('needs_research',)
    search_fields = ('name',)
    fieldsets = (
        ('Basic Information', {
            'fields': ('name', 'color')
        }),
        ('Research & Internal Notes', {
            'fields': ('needs_research', 'researcher_notes')
        }),
    )

class DiscoveryFilter(admin.SimpleListFilter):
    title = _('Discovery')
    parameter_name = 'discovery'

    def lookups(self, request, model_admin):
        return (
            ('others', _("Show others' items")),
        )

    def queryset(self, request, queryset):
        if self.value() == 'others':
            return queryset.exclude(owner=request.user)
        return queryset

class ViewModeFilter(admin.SimpleListFilter):
    title = _('View Mode')
    parameter_name = 'view'

    def lookups(self, request, model_admin):
        return (
            ('rels', _('Relationships (Timelines/People)')),
            ('research', _('Research (Notes/Status)')),
        )

    def queryset(self, request, queryset):
        return queryset

class OwnedAdmin(admin.ModelAdmin):
    readonly_fields = ('owner',)
    """
    Mixin to enforce ownership in the admin.
    Users only see their own data by default, unless they are superusers or discovery is on.
    Provides a 'Clone to My Collection' action.
    """
    def save_model(self, request, obj, form, change):
        if not obj.owner_id:
            obj.owner = request.user
        super().save_model(request, obj, form, change)

    def save_formset(self, request, form, formset, change):
        instances = formset.save(commit=False)
        for instance in instances:
            if hasattr(instance, 'owner') and not instance.owner_id:
                instance.owner = request.user
            instance.save()
        formset.save_m2m()

    def add_view(self, request, form_url='', extra_context=None):
        clone_from_id = request.GET.get('clone_from')
        if clone_from_id:
            try:
                # Get the source object
                source_obj = self.model.objects.get(pk=clone_from_id)
                # Populate initial data from source
                initial = {}
                for field in source_obj._meta.fields:
                    if field.name not in ['id', 'pk', 'owner', 'created_at', 'updated_at']:
                        initial[field.name] = getattr(source_obj, field.name)
                
                # For M2M fields, we need to handle them after save or via initial if possible.
                # Standard Django add_view doesn't handle M2M initial data easily via request.GET.
                # We'll just pass them in extra_context or handle them in the template? 
                # Better: override get_changeform_initial_data if possible.
                
                # Actually, let's just use the 'initial' parameter in GET if it's simple, 
                # but for a full clone, it's easier to just pass a custom initial dict.
                pass
            except self.model.DoesNotExist:
                pass
        return super().add_view(request, form_url, extra_context)

    def get_changeform_initial_data(self, request):
        initial = super().get_changeform_initial_data(request)
        clone_id = request.GET.get('clone_from')
        if clone_id:
            try:
                obj = self.model.objects.get(pk=clone_id)
                for field in obj._meta.fields:
                    if field.name not in ['id', 'pk', 'owner', 'created_at', 'updated_at', 'researcher_notes', 'needs_research']:
                        initial[field.name] = getattr(obj, field.name)
                
                # Explicitly clear research fields for clones
                initial['researcher_notes'] = ""
                initial['needs_research'] = False
                
                # Special handling for M2M if needed (though initial doesn't support list of IDs easily for all widgets)
                if hasattr(obj, 'people'):
                    initial['people'] = [p.pk for p in obj.people.all()]
                if hasattr(obj, 'timelines'):
                    initial['timelines'] = [t.pk for t in obj.timelines.all()]
                    
            except self.model.DoesNotExist:
                pass
        return initial

    def get_queryset(self, request):
        qs = super().get_queryset(request)
        if request.user.is_superuser:
            return qs
        
        # If 'others' filter is active, it's handled by DiscoveryFilter.queryset
        # But we need a default behavior: show only own items if NO filter is set.
        if 'discovery' in request.GET:
            return qs

        return qs.filter(owner=request.user)

    def has_change_permission(self, request, obj=None):
        if obj is not None and not request.user.is_superuser and obj.owner != request.user:
            if not request.user.groups.filter(name='Researchers').exists():
                return False
        return super().has_change_permission(request, obj)

    def has_delete_permission(self, request, obj=None):
        if obj is not None and not request.user.is_superuser and obj.owner != request.user:
            if not request.user.groups.filter(name='Researchers').exists():
                return False
        return super().has_delete_permission(request, obj)

    @admin.display(description='Copy')
    def clone_link(self, obj):
        from django.utils.html import format_html
        from django.urls import reverse
        # We'll use JS to hide this if it belongs to the current user
        # We tag it with the owner ID/name for easy identification
        owner_name = obj.owner.username if obj.owner else "none"
        return format_html('<a class="button clone-btn-list" data-owner="{}" href="{}?clone_from={}" style="background-color: #2563EB; color: white; padding: 2px 8px; border-radius: 4px; font-size: 10px;">Quick Copy</a>', 
                           owner_name, reverse(f'admin:timeline_{obj._meta.model_name}_add'), obj.pk)

    @admin.display(description='Owner')
    def owner_display(self, obj):
        from django.utils.html import format_html
        owner_name = obj.owner.username if obj.owner else "None"
        return format_html('<span class="owner-cell" data-username="{}">{}</span>', owner_name, owner_name)

    @admin.action(description="Quick Copy selected to my collection")
    def clone_to_my_collection(self, request, queryset):
        count = 0
        for obj in queryset:
            # Create a true new instance
            orig_pk = obj.pk
            orig_obj = self.model.objects.get(pk=orig_pk)
            obj.pk = None
            obj.owner = request.user
            obj.cloned_from = orig_obj
            obj.save()
            new_obj = obj
            
            # Handle ManyToMany fields safely
            # Re-fetch original to get relationships
            orig_obj = self.model.objects.get(pk=orig_pk)
            
            if hasattr(orig_obj, 'people'):
                new_obj.people.set(orig_obj.people.all())
            if hasattr(orig_obj, 'timelines'):
                # ONLY keep links to timelines owned by the current user
                # to avoid polluting other people's timelines with clones
                new_obj.timelines.set(orig_obj.timelines.filter(owner=request.user))
            
            # Privacy: Clear research notes on clone
            new_obj.researcher_notes = ""
            new_obj.needs_research = False
            new_obj.save()
            
            count += 1
        self.message_user(request, f"Successfully copied {count} items to your collection.")

@admin.register(Source)
class SourceAdmin(OwnedAdmin):
    list_select_related = ('owner', 'parent')
    list_display = ('title', 'parent', 'author', 'publication_date', 'needs_research', 'is_private', 'owner_display')
    search_fields = ('title', 'author', 'url', 'owner__username')
    list_filter = (DiscoveryFilter, 'owner', 'needs_research', 'is_private', 'tags')
    autocomplete_fields = ('parent',)
    filter_horizontal = ('tags',)
    actions = ['clone_to_my_collection']

@admin.register(Timeline)
class TimelineAdmin(OwnedAdmin):
    list_select_related = ('owner', 'parent')
    @admin.action(description="🚀 Full Deep Copy (including events in background)")
    def full_deep_copy(self, request, queryset):
        from .tasks import process_full_deep_copy
        count = 0
        for timeline in queryset:
            process_full_deep_copy(timeline.pk, request.user.pk)
            count += 1
        self.message_user(request, f"Scheduled {count} full deep copies. These will be processed in the background.")

    @admin.display(description='Import')
    def import_gedcom_link(self):
        from django.utils.html import format_html
        from django.urls import reverse
        return format_html('<a class="button" href="{}" style="background-color: #7C3AED; color: white; padding: 4px 12px; border-radius: 4px; font-weight: bold;">GEDCOM Import</a>', 
                           reverse('import_gedcom'))

    list_display = ('name', 'owner_display', 'parent', 'is_default', 'is_private', 'needs_research', 'clone_link')
    search_fields = ('name', 'parent__name', 'owner__username')
    list_filter = (DiscoveryFilter, 'owner', 'needs_research', 'is_private', 'parent', 'is_default')
    autocomplete_fields = ('parent',)
    actions = ['clone_to_my_collection', 'full_deep_copy']
    fieldsets = (
        ('Timeline Configuration', {
            'fields': ('name', 'parent', 'description', 'is_default', 'is_private')
        }),
        ('Research & Internal Notes', {
            'fields': ('needs_research', 'researcher_notes')
        }),
    )

    def get_readonly_fields(self, request, obj=None):
        readonly = super().get_readonly_fields(request, obj)
        if not request.user.is_superuser:
            if 'is_default' not in readonly:
                return list(readonly) + ['is_default']
        return readonly

class LocationAttachmentInline(admin.TabularInline):
    model = Attachment.locations.through
    extra = 1
    verbose_name = "Attachment"
    verbose_name_plural = "Attachments"

class LocationAliasInline(admin.TabularInline):
    model = LocationAlias
    extra = 1

class DisputedFactInline(GenericTabularInline):
    model = DisputedFact
    extra = 1

class PublicCommentInline(GenericTabularInline):
    model = PublicComment
    extra = 0
    readonly_fields = ('author_name', 'email', 'body', 'created_at')
    can_delete = False

class ResearchQuestionInline(GenericTabularInline):
    model = ResearchQuestion
    extra = 1
    fields = ('question', 'status', 'priority')

@admin.register(Location)
class LocationAdmin(SimpleHistoryAdmin, OwnedAdmin):
    list_select_related = ('owner', 'parent')
    inlines = [ResearchQuestionInline, LocationAliasInline, LocationAttachmentInline, DisputedFactInline, PublicCommentInline]
    list_display = ('name', 'owner_display', 'parent', 'status', 'is_private', 'needs_research', 'coordinates', 'has_image', 'clone_link')

    @admin.display(description='Image', boolean=True)
    def has_image(self, obj):
        return bool(obj.image)
    search_fields = ('name', 'parent__name', 'owner__username', 'aliases__name')
    list_filter = (DiscoveryFilter, 'owner', 'needs_research', 'is_private', 'status', 'parent', 'tags')
    autocomplete_fields = ('parent', 'coordinates_source', 'established_date_source', 'ceased_date_source')
    filter_horizontal = ('description_sources', 'tags')
    actions = ['clone_to_my_collection']

    fieldsets = (
        ('Basic Information', {
            'fields': ('name', 'parent', 'status', 'is_private', 'image', 'link', 'description', 'description_sources', 'tags')
        }),
        ('Geography', {
            'fields': (
                'coordinates',
                'coordinates_source'
            )
        }),
        ('Timeline Dates', {
            'fields': (
                ('established_date', 'established_date_precision', 'established_date_granularity', 'established_date_source'),
                ('ceased_date', 'ceased_date_precision', 'ceased_date_granularity', 'ceased_date_source')
            )
        }),
        ('Research & Internal Notes', {
            'fields': ('needs_research', 'researcher_notes')
        }),
    )


    class Media:
        js = ('timeline/js/admin_ai.js',)
        css = {
            'all': ('timeline/css/admin_ai.css',)
        }

class PersonRelationshipInline(admin.TabularInline):
    model = PersonRelationship
    fk_name = 'from_person'
    extra = 1
    autocomplete_fields = ('to_person',)

class PersonAttachmentInline(admin.TabularInline):
    model = Attachment.people.through
    extra = 1
    verbose_name = "Attachment"
    verbose_name_plural = "Attachments"

@admin.register(Person)
class PersonAdmin(SimpleHistoryAdmin, OwnedAdmin):
    list_select_related = ('owner',)
    list_display = ('name', 'owner_display', 'disambiguation', 'status', 'is_private', 'needs_research', 'birth_date', 'death_date', 'clone_link')
    search_fields = ('name', 'disambiguation', 'owner__username', 'birth_location__aliases__name', 'death_location__aliases__name')
    list_filter = (DiscoveryFilter, 'owner', 'needs_research', 'is_private', 'status', 'tags')
    inlines = [ResearchQuestionInline, PersonRelationshipInline, PersonAttachmentInline, DisputedFactInline, PublicCommentInline]
    autocomplete_fields = ('birth_location', 'death_location', 'birth_date_source', 'birth_location_source', 'death_date_source', 'death_location_source', 'burial_location_source')
    filter_horizontal = ('description_sources', 'tags')
    actions = ['clone_to_my_collection']

    fieldsets = (
        ('Basic Information', {
            'fields': (('name', 'gender', 'gender_custom'), 'status', 'is_private', 'disambiguation', 'image', 'link', 'description', 'description_sources', 'tags')
        }),
        ('Birth', {
            'fields': (
                ('birth_date', 'birth_date_precision', 'birth_date_granularity', 'birth_date_source'),
                ('birth_location', 'birth_location_source')
            )
        }),
        ('Death', {
            'fields': (
                ('death_date', 'death_date_precision', 'death_date_granularity', 'death_date_source'),
                ('death_location', 'death_location_source'),
                ('burial_location', 'burial_location_source')
            )
        }),
        ('Research & Internal Notes', {
            'fields': ('needs_research', 'researcher_notes')
        }),
    )


    class Media:
        js = ('timeline/js/admin_ai.js',)
        css = {
            'all': ('timeline/css/admin_ai.css',)
        }

class EventImageInline(admin.TabularInline):
    model = EventImage
    extra = 1

class EventAttachmentInline(admin.TabularInline):
    model = Attachment.events.through
    extra = 1
    verbose_name = "Attachment"
    verbose_name_plural = "Attachments"

class StoryEventInline(admin.TabularInline):
    model = StoryEvent
    extra = 1
    autocomplete_fields = ('story', 'event')

@admin.register(TimelineEvent)
class TimelineEventAdmin(SimpleHistoryAdmin, OwnedAdmin):
    list_select_related = ('owner', 'location')
    list_prefetch_related = ('people', 'timelines')
    inlines = [ResearchQuestionInline, EventImageInline, EventAttachmentInline, StoryEventInline, DisputedFactInline, PublicCommentInline]
    
    def get_list_display(self, request):
        view = request.GET.get('view')
        base = ['title', 'owner_display']
        if view == 'rels':
            return base + ['display_people', 'display_timelines', 'location', 'is_private', 'clone_link']
        elif view == 'research':
            return base + ['status', 'needs_research', 'is_private', 'researcher_notes_summary', 'clone_link']
        return ['title', 'owner_display', 'status', 'needs_research', 'is_private', 'start_date', 'end_date', 'location', 'clone_link']

    @admin.display(description='People')
    def display_people(self, obj):
        return ", ".join([p.name for p in obj.people.all()])

    @admin.display(description='Timelines')
    def display_timelines(self, obj):
        return ", ".join([t.name for t in obj.timelines.all()])

    @admin.display(description='Notes Summary')
    def researcher_notes_summary(self, obj):
        if not obj.researcher_notes:
            return ""
        return (obj.researcher_notes[:75] + '...') if len(obj.researcher_notes) > 75 else obj.researcher_notes

    list_filter = (ViewModeFilter, DiscoveryFilter, 'owner', 'is_private', 'needs_research', 'status', 'timelines', 'people', 'location', 'start_date', 'tags')
    search_fields = ('title', 'description', 'people__name', 'people__birth_location__aliases__name', 'people__death_location__aliases__name', 'timelines__name', 'owner__username', 'location__aliases__name', 'end_location__aliases__name')
    autocomplete_fields = ('location', 'end_location', 'people', 'timelines', 'start_date_source', 'end_date_source', 'location_source', 'end_location_source')
    filter_horizontal = ('description_sources', 'tags')
    actions = ['clone_to_my_collection']

    fieldsets = (
        ('Core Event details', {
            'fields': ('title', 'status', 'is_private', 'image', 'link', 'description', 'description_sources', 'tags')
        }),
        ('Start Date', {
            'fields': (
                ('start_date', 'start_date_precision', 'start_date_granularity', 'start_date_source'),
            )
        }),
        ('End Date', {
            'fields': (
                ('end_date', 'end_date_precision', 'end_date_granularity', 'end_date_source'),
            )
        }),
        ('Location', {
            'fields': (
                ('location', 'location_source'),
                ('end_location', 'end_location_source'),
            )
        }),
        ('Relationships', {
            'fields': ('people', 'timelines')
        }),
        ('Advanced Options', {
            'classes': ('collapse',),
            'fields': ('is_auto_generated',)
        }),
        ('Research & Internal Notes', {
            'fields': ('needs_research', 'researcher_notes')
        }),
    )


    class Media:
        js = ('timeline/js/admin_ai.js',)
        css = {
            'all': ('timeline/css/admin_ai.css',)
        }

@admin.register(Attachment)
class AttachmentAdmin(OwnedAdmin):
    list_display = ('title', 'file_type', 'owner')
    list_filter = ('file_type',)
    search_fields = ('title', 'description')
    filter_horizontal = ('events', 'people', 'locations', 'sources')

@admin.register(Story)
class StoryAdmin(OwnedAdmin):
    list_select_related = ('owner',)
    list_display = ('title', 'owner_display', 'color', 'is_private', 'needs_research', 'clone_link')
    search_fields = ('title', 'description', 'owner__username')
    list_filter = (DiscoveryFilter, 'owner', 'needs_research', 'is_private', 'tags')
    filter_horizontal = ('tags',)
    actions = ['clone_to_my_collection']
    inlines = [ResearchQuestionInline, StoryEventInline, PublicCommentInline]
    fieldsets = (
        ('Story Details', {
            'fields': ('title', 'description', 'color', 'is_private', 'tags')
        }),
        ('Research & Internal Notes', {
            'fields': ('needs_research', 'researcher_notes')
        }),
    )

@admin.register(DisputedFact)
class DisputedFactAdmin(OwnedAdmin):
    list_display = ('field_name', 'alternative_value', 'content_type', 'object_id', 'content_object', 'owner_display', 'is_resolved')
    list_filter = ('is_resolved', 'field_name', 'owner', 'content_type')
    search_fields = ('field_name', 'alternative_value', 'notes', 'owner__username')
    autocomplete_fields = ('source',)
    actions = ['clone_to_my_collection']

@admin.register(PublicComment)
class PublicCommentAdmin(admin.ModelAdmin):
    list_display = ('author_name', 'content_type', 'content_object', 'status', 'created_at', 'target_owner')
    list_filter = ('status', 'content_type', 'target_owner')
    search_fields = ('author_name', 'email', 'body')
    readonly_fields = ('author_name', 'email', 'body', 'content_type', 'object_id', 'target_owner', 'created_at')

    def get_queryset(self, request):
        qs = super().get_queryset(request)
        if request.user.is_superuser:
            return qs
        return qs.filter(target_owner=request.user)

    def has_change_permission(self, request, obj=None):
        if obj is not None and not request.user.is_superuser and obj.target_owner != request.user:
            return False
        return True

    def has_delete_permission(self, request, obj=None):
        if obj is not None and not request.user.is_superuser and obj.target_owner != request.user:
            return False
        return True

@admin.register(ResearchQuestion)
class ResearchQuestionAdmin(OwnedAdmin):
    list_display = ('question', 'content_type', 'content_object', 'status', 'priority', 'owner_display', 'created_at')
    list_filter = ('status', 'priority', 'content_type', 'owner')
    search_fields = ('question', 'answer', 'owner__username')


@admin.register(HelpCategory)
class HelpCategoryAdmin(admin.ModelAdmin):
    list_display = ('name', 'order')
    list_editable = ('order',)

class HelpImageInline(admin.TabularInline):
    model = HelpImage
    extra = 1

@admin.register(HelpTopic)
class HelpTopicAdmin(admin.ModelAdmin):
    list_display = ('title', 'category', 'order', 'is_published')
    list_filter = ('category', 'is_published')
    list_editable = ('order', 'is_published')
    search_fields = ('title', 'content')
    prepopulated_fields = {'slug': ('title',)}
    inlines = [HelpImageInline]
