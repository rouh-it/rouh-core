from django.db import migrations


def forget(apps, schema_editor):
    """Every saved "Start new chats like this" (`user_settings` named chat_options) is forgotten, and the
    "keep" it left on each chat with it: a chat's mode is its own now, like its model, and every new chat
    starts on Rouh's default (Full; Simple for an incognito chat)."""
    apps.get_model("rouh", "UserSetting").objects.filter(name="chat_options").delete()
    Chat = apps.get_model("rouh", "Chat")
    for row in Chat.objects.filter(reading__has_key="keep").only("id", "reading"):
        reading = {k: v for k, v in (row.reading or {}).items() if k != "keep"}
        Chat.objects.filter(id=row.id).update(reading=reading)


class Migration(migrations.Migration):
    """Chat Options without "Start new chats like this" (Petar, 16 November 2026: "remove start new chats like
    this behavior should be like smart/cheap selection"): what it saved for new chats is forgotten."""

    dependencies = [("rouh", "0255_permission_gates")]
    operations = [migrations.RunPython(forget, migrations.RunPython.noop)]
