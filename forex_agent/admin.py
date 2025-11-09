from django.contrib import admin
from django.utils.html import format_html
from .models import RawContent, ProcessedContent, ConversationHistory

# ==============================================================================
# ADMIN CONFIGURATION: RawContent
# ==============================================================================
# This admin interface is designed as a control panel for the data ingestion
# pipeline. An admin can monitor the queue of unprocessed content and manually
# intervene if necessary.
# ==============================================================================

@admin.register(RawContent)
class RawContentAdmin(admin.ModelAdmin):
    """
    Admin view for managing the raw content staging area.
    """
    
    # list_display: Controls the columns shown in the main list view.
    # We prioritize seeing the status (is_processed), title, content type,
    # and when it was created.
    list_display = (
        'title', 
        'content_type', 
        'get_status', # A custom method for color-coded status
        'created_at',
        'source_link', # A custom method to provide a clickable link
    )
    
    # list_filter: Adds a sidebar for filtering content. This is crucial for
    # quickly finding all unprocessed items or items of a specific type.
    list_filter = ('is_processed', 'content_type')
    
    # search_fields: Enables a search bar to look up content by its title or URL.
    search_fields = ('title', 'source_url')
    
    # readonly_fields: Prevents editing of fields that are set automatically.
    readonly_fields = ('id', 'created_at')

    # Custom Admin Actions: These add dropdown actions to the admin list view.
    # This action allows an admin to select items and re-queue them for processing.
    actions = ['mark_as_unprocessed']

    # Fieldsets organize the detail view for better readability.
    fieldsets = (
        ('Content Details', {
            'fields': ('title', 'source_url', 'content_type', 'raw_content')
        }),
        ('Processing Status', {
            'fields': ('is_processed', 'published_at_str')
        }),
        ('Metadata', {
            'fields': ('id', 'created_at')
        }),
    )

    def get_status(self, obj):
        """Custom method to display the processing status with a color code."""
        if obj.is_processed:
            return format_html('<span style="color: green;">● Processed</span>')
        return format_html('<span style="color: orange;">● Raw</span>')
    get_status.short_description = 'Status'

    def source_link(self, obj):
        """Custom method to make the source URL a clickable link."""
        return format_html('<a href="{}" target="_blank">View Source</a>', obj.source_url)
    source_link.short_description = 'Original Source'

    def mark_as_unprocessed(self, request, queryset):
        """Admin action to mark selected content as not processed."""
        queryset.update(is_processed=False)
    mark_as_unprocessed.short_description = "Re-queue selected content for processing"


# ==============================================================================
# ADMIN CONFIGURATION: ProcessedContent
# ==============================================================================
# This interface is the main dashboard for the agent's "long-term memory".
# It's designed for reviewing and managing the curated, final content. The critical
# 'embedding' field is protected from editing.
# ==============================================================================

@admin.register(ProcessedContent)
class ProcessedContentAdmin(admin.ModelAdmin):
    """
    Admin view for managing the AI-processed knowledge base.
    """
    
    # list_display: Shows the most relevant info at a glance.
    list_display = ('title', 'content_type', 'published_at', 'updated_at')
    
    # list_filter: Allows filtering by content type and publication date.
    list_filter = ('content_type', 'published_at')
    
    # search_fields: Crucial for finding information within the knowledge base.
    # We include 'processed_content' to allow full-text search.
    search_fields = ('title', 'source_url', 'processed_content')
    
    # date_hierarchy: Adds handy drill-down navigation by date.
    date_hierarchy = 'published_at'
    
    # readonly_fields: Protects all machine-generated or immutable data.
    # It is *critical* that the 'embedding' field is not editable.
    readonly_fields = (
        'id', 
        'embedding', 
        'created_at', 
        'updated_at'
    )
    
    # fieldsets: Organizes the detail view into logical sections.
    # We place the embedding in a "Technical Details" section to signify
    # that it's not meant for human consumption.
    fieldsets = (
        ('Source Information', {
            'fields': ('title', 'source_url', 'content_type', 'published_at')
        }),
        ('AI Processed Output', {
            'fields': ('processed_content',)
        }),
        ('Technical Details', {
            'classes': ('collapse',), # Start as a collapsed section
            'fields': ('id', 'embedding')
        }),
        ('Timestamps', {
            'fields': ('created_at', 'updated_at')
        }),
    )

# ==============================================================================
# ADMIN CONFIGURATION: ConversationHistory
# ==============================================================================
# This model is for auditing and debugging. Therefore, the admin interface
# should be strictly read-only to ensure the integrity of the historical logs.
# No one should be able to add, change, or delete conversation records from here.
# ==============================================================================

@admin.register(ConversationHistory)
class ConversationHistoryAdmin(admin.ModelAdmin):
    """
    Read-only admin view for auditing agent-user interactions.
    """
    
    # list_display: Shows a summary of each interaction.
    list_display = ('context_id', 'timestamp', 'get_user_message_snippet')
    
    # search_fields: Allows searching for specific conversations by context ID
    # or content within the messages.
    search_fields = ('context_id', 'user_message', 'agent_message')
    
    # readonly_fields: Makes all fields non-editable in the detail view.
    readonly_fields = ('context_id', 'user_message', 'agent_message', 'timestamp')

    # list_filter: Filter conversations by the date they occurred.
    list_filter = ('timestamp',)

    def get_user_message_snippet(self, obj):
        """Returns a truncated version of the user message for the list view."""
        return (obj.user_message[:75] + '...') if len(obj.user_message) > 75 else obj.user_message
    get_user_message_snippet.short_description = 'User Message'

    # --- PERMISSION OVERRIDES FOR STRICT READ-ONLY BEHAVIOR ---
    
    def has_add_permission(self, request):
        """Prevent anyone from adding new history records via the admin."""
        return False

    def has_change_permission(self, request, obj=None):
        """Prevent anyone from changing existing history records."""
        return False

    # def has_delete_permission(self, request, obj=None):
    #     """
    #     Prevent deletion of individual records. To delete history, a specific
    #     data retention script should be used. This prevents accidental data loss.
    #     """
    #     return False