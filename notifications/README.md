# Notification Structure Standard

This directory contains notifications that are consumed by Vesta. All notification creators MUST follow this structure.

## File Format
- **Filename**: `{timestamp_nanoseconds}-{source}-{type}.json`
- **Example**: `1736943045000000-whatsapp-message.json`

## JSON Structure

```json
{
  "timestamp": "2025-09-15T10:30:45Z",  // RFC3339 format, REQUIRED
  "source": "whatsapp",                  // Source system identifier, REQUIRED
  "type": "message",                     // Notification type, REQUIRED
  "message": "Primary message content",  // Human-readable message, REQUIRED
  "metadata": {                          // All additional data, OPTIONAL
    // Any key-value pairs specific to this notification
    // These are automatically passed to Vesta without code changes
  }
}
```

## Required Fields
- `timestamp`: When the notification was created (RFC3339 format)
- `source`: System that created the notification (e.g., "whatsapp", "scheduler", "email")
- `type`: Type of notification (e.g., "message", "reminder", "alert")
- `message`: Primary human-readable content that will be shown to the user

## Optional Fields
- `metadata`: Object containing any additional data. ALL fields here are automatically included in prompts to Vesta

## Examples

### WhatsApp Message
```json
{
  "timestamp": "2025-09-15T10:30:45Z",
  "source": "whatsapp",
  "type": "message",
  "message": "Hello, how are you?",
  "metadata": {
    "chat_jid": "1234567890@s.whatsapp.net",
    "chat_name": "John Doe",
    "sender": "1234567890",
    "is_forwarded": true,
    "media_type": "image"
  }
}
```

### Scheduler Reminder
```json
{
  "timestamp": "2025-09-15T14:00:00Z",
  "source": "scheduler",
  "type": "reminder",
  "message": "Team meeting in 15 minutes",
  "metadata": {
    "reminder_id": "meeting_123",
    "priority": "high",
    "recurring": false
  }
}
```

## Consumer Behavior

Vesta will:
1. Display the `message` field to the user
2. Include ALL metadata fields in the prompt sent to Claude
3. Format display based on `source` and `type`
4. Pass through any new metadata fields WITHOUT requiring code changes

## Adding New Metadata

To add new metadata to notifications:
1. Simply add the field to the `metadata` object
2. Vesta will automatically include it in prompts
3. No code changes needed in main.py

Example: Adding location to WhatsApp messages:
```json
{
  "timestamp": "2025-09-15T10:30:45Z",
  "source": "whatsapp",
  "type": "message",
  "message": "I'm here!",
  "metadata": {
    "chat_name": "John Doe",
    "latitude": 37.7749,
    "longitude": -122.4194,
    "location_name": "San Francisco"
  }
}
```

Vesta will automatically receive: "From John Doe (metadata: latitude=37.7749, longitude=-122.4194, location_name=San Francisco): I'm here!"