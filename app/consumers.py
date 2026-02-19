import json
from channels.generic.websocket import AsyncWebsocketConsumer
from django.contrib.auth import get_user_model
from channels.db import database_sync_to_async
from .models import Conversation, Message

User = get_user_model()


class PresenceConsumer(AsyncWebsocketConsumer):
    """Handles user presence updates for the user list"""

    async def connect(self):
        self.user = self.scope["user"]

        # block anonymous users
        if self.user.is_anonymous:
            await self.close()
            return

        # all users subscribe to presence group
        self.presence_group = "presence"

        await self.channel_layer.group_add(
            self.presence_group,
            self.channel_name
        )

        # mark user online
        await self.update_user_status(True)

        # notify others user is online
        await self.channel_layer.group_send(
            self.presence_group,
            {
                "type": "user_presence",
                "user_id": self.user.id,
                "username": self.user.username,
                "is_online": True,
            },
        )

        await self.accept()

    async def disconnect(self, close_code):
        if hasattr(self, "presence_group"):
            await self.update_user_status(False)

            # notify others user is offline
            await self.channel_layer.group_send(
                self.presence_group,
                {
                    "type": "user_presence",
                    "user_id": self.user.id,
                    "username": self.user.username,
                    "is_online": False,
                },
            )

            await self.channel_layer.group_discard(
                self.presence_group,
                self.channel_name
            )

    async def user_presence(self, event):
        """Send presence update to browser"""
        await self.send(text_data=json.dumps({
            "type": "presence",
            "user_id": event["user_id"],
            "username": event["username"],
            "is_online": event["is_online"],
        }))

    @database_sync_to_async
    def update_user_status(self, status):
        try:
            user = User.objects.get(id=self.user.id)
            user.is_online = status
            user.save(update_fields=["is_online"])
        except Exception as e:
            print("Status update error:", e)


class ChatConsumer(AsyncWebsocketConsumer):

    async def connect(self):
        self.user = self.scope["user"]
        self.other_user_id = self.scope["url_route"]["kwargs"]["user_id"]

        # block anonymous users
        if self.user.is_anonymous:
            await self.close()
            return

        # create consistent room name
        user_ids = sorted([self.user.id, int(self.other_user_id)])
        self.room_group_name = f"chat_{user_ids[0]}_{user_ids[1]}"

        # join room
        await self.channel_layer.group_add(
            self.room_group_name,
            self.channel_name
        )

        # mark online
        await self.update_user_status(True)

        # notify others
        await self.channel_layer.group_send(
            self.room_group_name,
            {
                "type": "user_status",
                "user_id": self.user.id,
                "is_online": True,
            },
        )

        await self.accept()

    async def disconnect(self, close_code):
        if hasattr(self, "room_group_name"):
            await self.channel_layer.group_discard(
                self.room_group_name,
                self.channel_name
            )

        await self.update_user_status(False)

        # notify others user offline
        if hasattr(self, "room_group_name"):
            await self.channel_layer.group_send(
                self.room_group_name,
                {
                    "type": "user_status",
                    "user_id": self.user.id,
                    "is_online": False,
                },
            )

    async def receive(self, text_data):
        data = json.loads(text_data)
        msg_type = data.get("type", "message")

        if msg_type == "message":
            message_text = data.get("message", "").strip()

            if not message_text:
                return

            # save message
            message = await self.save_message(message_text)

            if not message:
                return

            # broadcast message with ID
            await self.channel_layer.group_send(
                self.room_group_name,
                {
                    "type": "chat_message",
                    "message_id": message.id,
                    "message": message.content,
                    "sender_id": self.user.id,
                    "sender_name": self.user.username,
                    "timestamp": message.timestamp.strftime("%H:%M"),
                },
            )
        
        elif msg_type == "mark_as_read":
            # Mark messages as read
            message_ids = data.get("message_ids", [])
            if message_ids:
                await self.mark_messages_read(message_ids, self.user.id)
                
                # Notify the sender about read receipts
                await self.channel_layer.group_send(
                    self.room_group_name,
                    {
                        "type": "message_read",
                        "message_ids": message_ids,
                    },
                )
        
        elif msg_type == "typing":
            # Broadcast typing indicator
            await self.channel_layer.group_send(
                self.room_group_name,
                {
                    "type": "typing",
                    "user_id": self.user.id,
                },
            )
        
        elif msg_type == "stop_typing":
            # Broadcast stop typing
            await self.channel_layer.group_send(
                self.room_group_name,
                {
                    "type": "stop_typing",
                    "user_id": self.user.id,
                },
            )
        
        elif msg_type == "delete_message":
            # Delete message
            message_id = data.get("message_id")
            if message_id:
                await self.delete_message(message_id, self.user.id)
                
                # Notify others about deletion
                await self.channel_layer.group_send(
                    self.room_group_name,
                    {
                        "type": "deleted",
                        "message_id": message_id,
                    },
                )

    async def chat_message(self, event):
        """Send message to browser"""
        await self.send(text_data=json.dumps({
            "type": "message",
            "message_id": event["message_id"],
            "message": event["message"],
            "sender_id": event["sender_id"],
            "sender_name": event["sender_name"],
            "timestamp": event["timestamp"],
        }))
    
    async def message_read(self, event):
        """Send read receipt to browser"""
        await self.send(text_data=json.dumps({
            "type": "read",
            "message_ids": event["message_ids"],
        }))

    async def typing(self, event):
        """Broadcast typing indicator"""
        if event["user_id"] != self.user.id:
            await self.send(text_data=json.dumps({
                "type": "typing",
                "user_id": event["user_id"],
            }))

    async def stop_typing(self, event):
        """Broadcast stop typing"""
        if event["user_id"] != self.user.id:
            await self.send(text_data=json.dumps({
                "type": "stop_typing",
                "user_id": event["user_id"],
            }))

    async def deleted(self, event):
        """Broadcast message deletion"""
        await self.send(text_data=json.dumps({
            "type": "deleted",
            "message_id": event["message_id"],
        }))

    async def user_status(self, event):
        """Send online/offline updates"""
        await self.send(text_data=json.dumps({
            "type": "status",
            "user_id": event["user_id"],
            "is_online": event["is_online"],
        }))

    # -------------------------
    # DATABASE OPERATIONS
    # -------------------------

    @database_sync_to_async
    def save_message(self, content):
        try:
            other_user = User.objects.get(id=self.other_user_id)

            # maintain consistent ordering
            user1, user2 = sorted([self.user, other_user], key=lambda u: u.id)

            conversation, _ = Conversation.objects.get_or_create(
                user1=user1,
                user2=user2
            )

            message = Message.objects.create(
                conversation=conversation,
                sender=self.user,
                content=content
            )

            return message

        except Exception as e:
            print("Message save error:", e)
            return None

    @database_sync_to_async
    def mark_messages_read(self, message_ids, reader_id):
        """Mark messages as read by the reader"""
        try:
            Message.objects.filter(
                id__in=message_ids,
                is_read=False
            ).exclude(sender_id=reader_id).update(is_read=True)
        except Exception as e:
            print("Mark read error:", e)

    @database_sync_to_async
    def delete_message(self, message_id, user_id):
        """Delete a message (only if user is the sender)"""
        try:
            Message.objects.filter(id=message_id, sender_id=user_id).delete()
        except Exception as e:
            print("Delete message error:", e)

    @database_sync_to_async
    def update_user_status(self, status):
        try:
            user = User.objects.get(id=self.user.id)
            user.is_online = status
            user.save(update_fields=["is_online"])
        except Exception as e:
            print("Status update error:", e)
