# forex_agent/models.py
import uuid
from django.db import models
from pgvector.django import VectorField




# ==============================================================================
# NEW MODEL: RawContent (Staging Table)
# ==============================================================================
# This model acts as a staging area for all fetched and scraped content
# before it is sent to the AI for processing. This decouples the fetching
# process from the AI processing, making the system more resilient.
# ==============================================================================

class RawContent(models.Model):
    """
    Stores raw, unprocessed content fetched from news APIs or web scraping.
    This serves as a queue for the AI processing tasks.
    """
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    source_url = models.URLField(unique=True, max_length=1000)
    title = models.CharField(max_length=255)
    raw_content = models.TextField()
    content_type = models.CharField(max_length=20, choices=[('article', 'Article'), ('news', 'News')])
    published_at_str = models.CharField(max_length=100, null=True, blank=True)
    is_processed = models.BooleanField(default=False, db_index=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['created_at']
        verbose_name = "Raw Content"
        verbose_name_plural = "Raw Contents"

    def __str__(self) -> str:
        return f"[{'PROCESSED' if self.is_processed else 'RAW'}] {self.title}"








# ==============================================================================
# MODEL: ProcessedContent
# ==============================================================================
# This is the agent's primary "long-term memory". It stores all AI-processed
# content, whether from news APIs or scraped educational articles. The vector
# embedding field is the key to enabling fast, semantic searches.
# ==============================================================================

class ProcessedContent(models.Model):
    """
    Stores curated, AI-processed educational content and news articles.
    """
    # Use a UUID for the primary key. This is a best practice for distributed systems
    # as it prevents ID collisions if you ever have multiple instances writing to the DB.
    id = models.UUIDField(
        primary_key=True, 
        default=uuid.uuid4, 
        editable=False,
        help_text="Unique identifier for each piece of content."
    )
    
    # The original URL of the content. This is crucial for tracking sources
    # and preventing duplicate entries during our scheduled scraping/fetching tasks.
    source_url = models.URLField(
        unique=True, 
        max_length=1000,
        help_text="The original URL of the content to prevent duplicates."
    )
    
    # A clean, human-readable title for the article.
    title = models.CharField(
        max_length=255,
        help_text="The original or AI-generated title of the content."
    )
    
    # CORRECTED: This field holds the clean, AI-articulated content.
    # Standardized to 'processed_content' for consistency across the app.
    processed_content = models.TextField(
        help_text="The AI-cleaned, summarized, and formatted content."
    )
    
    # --- The Core of our RAG (Retrieval-Augmented Generation) System ---
    # This VectorField, powered by the pgvector extension in PostgreSQL, stores
    # the numerical representation (embedding) of the 'processed_content'.
    # CORRECTED: Dimensions updated to 1536 to match 'openai/text-embedding-ada-002'.
    embedding = VectorField(
        dimensions=1536,
        help_text="Vector embedding of the processed text for semantic search."
    )
    
    # A field to distinguish between different types of content, allowing us
    # to easily query for only 'news' or only 'articles'.
    content_type = models.CharField(
        max_length=20, 
        choices=[('article', 'Article'), ('news', 'News')],
        db_index=True,
        help_text="Categorizes the content as educational (article) or timely (news)."
    )
    
    # The original publication date of the content, important for sorting news.
    # It's nullable as some scraped articles might not have a clear date.
    published_at = models.DateTimeField(
        null=True, 
        blank=True,
        help_text="The original publication date of the news or article, if available."
    )
    
    # Automatically records when this entry was first created in our database.
    created_at = models.DateTimeField(
        auto_now_add=True,
        help_text="Timestamp when the content was first added to our database."
    )
    
    # Automatically records when this entry was last updated.
    updated_at = models.DateTimeField(
        auto_now=True,
        help_text="Timestamp when the content was last updated."
    )

    class Meta:
        # By default, when we query for content, it will be sorted by the most recent first.
        ordering = ['-published_at', '-created_at']
        verbose_name = "Processed Content"
        verbose_name_plural = "Processed Contents"

    def __str__(self) -> str:
        """String representation of the model, useful for the Django admin panel."""
        return f"[{self.content_type.upper()}] {self.title}"



# ==============================================================================
# MODEL: ConversationHistory
# ==============================================================================
# This model acts as the agent's "short-term memory", allowing it to recall
# previous turns in a conversation with a specific user to provide
# contextually relevant follow-up answers.
# ==============================================================================

class ConversationHistory(models.Model):
    """
    Stores the history of interactions to provide context for conversations.
    """
    # The unique session or context ID, likely from the A2A protocol.
    # We add a database index (`db_index=True`) for very fast lookups of a conversation's history.
    context_id = models.CharField(
        max_length=255, 
        db_index=True,
        help_text="The unique session or context ID from the A2A protocol."
    )
    
    # The message sent by the user.
    user_message = models.TextField(
        help_text="The message sent by the user."
    )
    
    # The final response generated by the agent.
    agent_message = models.TextField(
        help_text="The response generated by the agent."
    )
    
    # Automatically records when this specific user-agent exchange happened.
    timestamp = models.DateTimeField(
        auto_now_add=True,
        help_text="Timestamp of the interaction."
    )

    class Meta:
        # Ensures that when we query for history, it's always in the correct chronological order.
        ordering = ['timestamp']
        # A more readable name for the model in the Django admin panel.
        verbose_name = "Conversation History"
        verbose_name_plural = "Conversation Histories"

    def __str__(self) -> str:
        """String representation of the model instance."""
        return f"Interaction in {self.context_id} at {self.timestamp.strftime('%Y-%m-%d %H:%M')}"
    




























