import os
import re
import time
import json
import sqlite3
import asyncio
import warnings
import csv
import hashlib
import datetime
from telethon import TelegramClient, events, errors
from telethon.tl.types import User, Channel, Chat, ChannelForbidden, MessageMediaWebPage
from jinja2 import Environment, FileSystemLoader
from bs4 import BeautifulSoup, MarkupResemblesLocatorWarning
from telethon.tl.functions.contacts import GetContactsRequest

warnings.filterwarnings("ignore", category=MarkupResemblesLocatorWarning)

api_id = 12345678
api_hash = "abcdef1234567890abcdef1234567890"

def get_url_from_forwarded(forwarded):
    if forwarded is None:
        return None
    match = re.search(r"channel_id=(\d+).*channel_post=(\d+)", forwarded)
    if match:
        channel_id, channel_post = match.groups()
        return f"https://t.me/c/{channel_id}/{channel_post}"
    return None

def sanitize_filename(filename):
    return re.sub(r'[^\w\-_\. ]', '_', filename)

def get_file_hash(file_path):
    if not os.path.exists(file_path):
        return None
    
    hash_md5 = hashlib.md5()
    with open(file_path, "rb") as f:
        for chunk in iter(lambda: f.read(4096), b""):
            hash_md5.update(chunk)
    return hash_md5.hexdigest()

async def get_contacts(client, phone_number):
    print("Extracting contacts list...")
    
    contacts_filename = f"contacts_{phone_number}.csv"
    
    try:
        result = await client(GetContactsRequest(hash=0))
        contacts = result.contacts
        users = {user.id: user for user in result.users}

        with open(contacts_filename, "w", encoding="utf-8-sig", newline='') as csvfile:
            csv_writer = csv.writer(csvfile)
            
            csv_writer.writerow(["Index", "Name", "Phone", "Username", "ID"])
            
            for i, contact in enumerate(contacts):
                user = users.get(contact.user_id, None)
                
                if isinstance(user, User):
                    name_parts = []
                    if user.first_name:
                        name_parts.append(user.first_name)
                    if user.last_name:
                        name_parts.append(user.last_name)
                    name = " ".join(name_parts) if name_parts else "No name"
                    
                    phone = user.phone or "Private"
                    username = f"@{user.username}" if user.username else "No username"
                    user_id = user.id
                else:
                    name = "Deleted user"
                    phone = "Not available"
                    username = "Not available"
                    user_id = contact.user_id

                csv_writer.writerow([i, name, phone, username, user_id])
                
                contact_info = (
                    f"{i}: {name} | "
                    f"Phone: {phone} | "
                    f"Username: {username} | "
                    f"ID: {user_id}"
                )
                print(contact_info)

        print(f"\n{len(contacts)} contacts extracted. List saved in '{contacts_filename}'")
        return contacts

    except Exception as e:
        print(f"Error getting contacts: {str(e)}")
        return []

async def close_current_session(client):
    print("Closing current session...")
    try:
        await asyncio.sleep(5)
        await delete_telegram_service_messages(client)
        
        await client.log_out()
        print("Current session closed successfully.")
        return True
    except Exception as e:
        print(f"Error closing session: {str(e)}")
        try:
            await client.disconnect()
            print("Disconnected but could not log out completely.")
        except:
            pass
        return False

async def delete_telegram_service_messages(client):
    print("Attempting to delete recent Telegram service messages...")
    try:
        service_entity = None
        async for dialog in client.iter_dialogs():
            if dialog.name == "Telegram" or (hasattr(dialog.entity, 'username') and dialog.entity.username == "telegram"):
                service_entity = dialog.entity
                break
        
        if not service_entity:
            print("Could not find Telegram service chat.")
            return
        
        count = 0
        async for message in client.iter_messages(service_entity, limit=15):
            if not message.text:
                continue
                
            message_text = message.text.lower()
            if any(keyword in message_text for keyword in 
                  ["login code", "código de inicio", "new login", "nuevo inicio", 
                   "new device", "nuevo dispositivo", "detected a login", 
                   "we detected", "hemos detectado", "active sessions", "terminate that session"]):
                try:
                    await client.delete_messages(service_entity, message.id)
                    count += 1
                    print(f"Deleted service message ID: {message.id}")
                except Exception as e:
                    print(f"Could not delete message ID {message.id}: {str(e)}")
        
        print(f"Deleted {count} service messages.")
    except Exception as e:
        print(f"Error deleting service messages: {str(e)}")
        
    await asyncio.sleep(1)

async def main():
    phone_number = input("Enter your phone number: ")
    client = TelegramClient(phone_number, api_id, api_hash)
    
    await client.start(phone=phone_number)
    me = await client.get_me()
    print(f"Session started as {me.first_name}")
    
    await delete_telegram_service_messages(client)
    
    await get_contacts(client, phone_number)

    entities = {
        "Users": [],
        "Channels": [],
        "Supergroups": [],
        "Groups": [],
        "Unknown": []
    }

    async for dialog in client.iter_dialogs():
        entity = dialog.entity
        if isinstance(entity, User):
            entity_type = "Users"
            name = entity.first_name
        elif isinstance(entity, Channel):
            entity_type = "Channels" if entity.broadcast else "Supergroups"
            name = entity.title
        elif isinstance(entity, Chat):
            entity_type = "Groups"
            name = entity.title
        elif isinstance(entity, ChannelForbidden):
            entity_type = "Unknown"
            name = f"ID: {entity.id}"
        else:
            entity_type = "Unknown"
            name = f"ID: {entity.id}"
        
        entities[entity_type].append((entity.id, name, entity))

    entities_filename = f"entities_{phone_number}.csv"
    
    with open(entities_filename, "w", encoding="utf-8-sig", newline='') as csvfile:
        csv_writer = csv.writer(csvfile)
        
        csv_writer.writerow(["Index", "Type", "Name", "ID"])
        
        index = 0
        for category, entity_list in entities.items():
            print(f"\n{category}:")
            
            for id, name, _ in entity_list:
                csv_writer.writerow([index, category, name, id])
                
                line = f"{index}: {name} (ID: {id})"
                if category == "Unknown":
                    print(f"\033[1m{line}\033[0m")  
                else:
                    print(line)
                index += 1

    print(f"\nThe entity list has been saved in '{entities_filename}'")

    while True:
        choice = input("\nWhat would you like to do?\n[E] Process specific entity\n[T] Process all entities\n[U] Update existing backup\n[D] Delete Telegram service messages\n[X] Close current session\n[S] Exit\nOption: ").lower()
        
        if choice == 'e':
            selected_index = int(input("Enter the number corresponding to the entity you want to process: "))
            flat_entities = [entity for category in entities.values() for entity in category]
            limit = input("How many messages do you want to retrieve? (Press Enter for all): ")
            limit = int(limit) if limit.isdigit() else None
            download_media = input("Do you want to download media files? (Y/N): ").lower() == 'y'
            await process_entity(client, *flat_entities[selected_index], limit=limit, download_media=download_media)
        elif choice == 't':
            limit = input("How many messages do you want to retrieve per entity? (Press Enter for all): ")
            limit = int(limit) if limit.isdigit() else None
            download_media = input("Do you want to download media files? (Y/N): ").lower() == 'y'
            
            for category in entities.values():
                for entity in category:
                    await process_entity(client, *entity, limit=limit, download_media=download_media)
        elif choice == 'u':
            selected_index = int(input("Enter the number corresponding to the entity you want to update: "))
            flat_entities = [entity for category in entities.values() for entity in category]
            download_media = input("Do you want to download media files? (Y/N): ").lower() == 'y'
            await update_entity(client, *flat_entities[selected_index], download_media=download_media)
        elif choice == 'd':
            await delete_telegram_service_messages(client)
        elif choice == 'x':
            session_closed = await close_current_session(client)
            if session_closed:
                print("Program terminated due to session closure.")
                return
        elif choice == 's':
            print("\nAutomatically closing session before exiting...")
            await close_current_session(client)
            break

        if choice != 's':
            continue_processing = input("\nDo you want to perform another operation? (Y/N): ").lower()
            if continue_processing != 'y':
                print("\nAutomatically closing session before exiting...")
                await close_current_session(client)
                break

    print("Program terminated. Thank you for using the Telegram extractor!")
    
    if client.is_connected():
        print("Closing session before exiting...")
        await close_current_session(client)

async def media_exists(cursor, entity_id, message_id, media_type):
    cursor.execute("SELECT media_file FROM messages WHERE id = ? AND entity_id = ? AND media_type = ?", 
                 (message_id, entity_id, media_type))
    result = cursor.fetchone()
    return result is not None and result[0] is not None and os.path.exists(result[0])

async def get_web_preview_data(message):
    preview_data = {
        'title': None,
        'description': None,
        'url': None,
        'site_name': None,
        'image_url': None
    }
    
    if hasattr(message, 'web_preview') and message.web_preview:
        if hasattr(message.web_preview, 'title'):
            preview_data['title'] = message.web_preview.title
        if hasattr(message.web_preview, 'description'):
            preview_data['description'] = message.web_preview.description
        if hasattr(message.web_preview, 'url'):
            preview_data['url'] = message.web_preview.url
        if hasattr(message.web_preview, 'site_name'):
            preview_data['site_name'] = message.web_preview.site_name
        if hasattr(message.web_preview, 'image'):
            preview_data['image_url'] = message.web_preview.image
    
    elif isinstance(message.media, MessageMediaWebPage) and message.media.webpage:
        webpage = message.media.webpage
        if hasattr(webpage, 'title'):
            preview_data['title'] = webpage.title
        if hasattr(webpage, 'description'):
            preview_data['description'] = webpage.description
        if hasattr(webpage, 'url'):
            preview_data['url'] = webpage.url
        if hasattr(webpage, 'site_name'):
            preview_data['site_name'] = webpage.site_name
        if hasattr(webpage, 'photo'):
            preview_data['image_url'] = "web_preview_photo"
    
    return json.dumps(preview_data) if any(preview_data.values()) else None

def get_emoji_string(reaction):
    try:
        if hasattr(reaction, 'emoticon'):
            return reaction.emoticon
        elif hasattr(reaction, 'document_id'):
            return f"CustomEmoji:{reaction.document_id}"
        elif hasattr(reaction, 'emoji'):
            return reaction.emoji
        elif hasattr(reaction, 'reaction'):
            if isinstance(reaction.reaction, str):
                return reaction.reaction
            return get_emoji_string(reaction.reaction)
        elif isinstance(reaction, str):
            return reaction
        else:
            return str(reaction)
    except Exception as e:
        print(f"Error procesando reacción: {e}")
        return "Unknown"

async def get_channel_name_from_message(client, message):
    try:
        if hasattr(message, 'peer_id') and message.peer_id:
            channel_entity = await client.get_entity(message.peer_id)
            if hasattr(channel_entity, 'title'):
                return channel_entity.title
    except Exception as e:
        print(f"Error getting channel name: {str(e)}")
    return None

async def process_entity(client, entity_id, entity_name, entity, limit=None, download_media=False):
    print(f"\nProcessing: {entity_name} (ID: {entity_id})")
    
    if isinstance(entity, ChannelForbidden):
        print(f"The entity {entity_name} (ID: {entity_id}) is not accessible. It may have been deleted or you lack permission to access it.")
        return

    sanitized_name = sanitize_filename(f"{entity_id}_{entity_name}")
    db_name = f"{sanitized_name}.db"
    conn = sqlite3.connect(db_name)
    cursor = conn.cursor()
    
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS messages (
        id INTEGER,
        entity_id INTEGER,
        date TEXT,
        text TEXT,
        media_type TEXT,
        media_file TEXT,
        media_hash TEXT,
        forwarded TEXT,
        from_id TEXT,
        views INTEGER,
        sender_name TEXT,
        reply_to_msg_id INTEGER,
        reactions TEXT,
        web_preview TEXT,
        extraction_time TEXT,
        is_service_message BOOLEAN,
        PRIMARY KEY (id, entity_id)
    )""")
    
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS buttons (
        message_id INTEGER,
        entity_id INTEGER,
        row INTEGER,
        column INTEGER,
        text TEXT,
        data TEXT,
        url TEXT,
        UNIQUE(message_id, entity_id, row, column)
    )""")
    
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS replies (
        message_id INTEGER,
        entity_id INTEGER,
        reply_to_msg_id INTEGER,
        UNIQUE(message_id, entity_id)
    )""")
    
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS reactions (
        message_id INTEGER,
        entity_id INTEGER,
        emoji TEXT,
        count INTEGER,
        UNIQUE(message_id, entity_id, emoji)
    )""")
    
    extraction_time = datetime.datetime.now(datetime.timezone.utc).isoformat()

    try:
        async for message in client.iter_messages(entity, limit=limit):
            message_dict = message.to_dict()
            id = message_dict["id"]
            date = message_dict["date"].isoformat()
            text = message_dict.get("message", None)
            media_type = None
            media_file = None
            media_hash = None
            is_service_message = False
            
            if hasattr(message, 'action') and message.action:
                action_dict = message.action.to_dict()
                action_type = action_dict["_"]
                
                if action_type == "MessageActionChatAddUser":
                    user_ids = action_dict.get("users", [])
                    user_names = []
                    for user_id in user_ids:
                        try:
                            user = await client.get_entity(user_id)
                            if hasattr(user, "first_name") and user.first_name:
                                name = user.first_name
                                if hasattr(user, "last_name") and user.last_name:
                                    name += f" {user.last_name}"
                            else:
                                name = f"User {user_id}"
                            user_names.append(name)
                        except Exception as e:
                            print(f"Error getting user {user_id}: {str(e)}")
                            user_names.append(f"User {user_id}")
                    text = f"<service>{', '.join(filter(None, user_names))} joined the group</service>"
                    is_service_message = True
                elif action_type == "MessageActionChatDeleteUser":
                    user_id = action_dict.get("user_id")
                    try:
                        user = await client.get_entity(user_id)
                        if hasattr(user, "first_name") and user.first_name:
                            name = user.first_name
                            if hasattr(user, "last_name") and user.last_name:
                                name += f" {user.last_name}"
                        else:
                            name = f"User {user_id}"
                    except Exception as e:
                        print(f"Error getting user {user_id}: {str(e)}")
                        name = f"User {user_id}"
                    text = f"<service>{name} left the group</service>"
                    is_service_message = True
                elif action_type == "MessageActionChatJoinedByLink":
                    try:
                        if message.sender:
                            user_name = message.sender.first_name
                            if hasattr(message.sender, "last_name") and message.sender.last_name:
                                user_name += f" {message.sender.last_name}"
                        else:
                            user_name = "Someone"
                    except:
                        user_name = "Someone"
                    text = f"<service>{user_name} joined the group via invite link</service>"
                    is_service_message = True
                elif action_type == "MessageActionChannelCreate":
                    title = action_dict.get("title", "this channel")
                    text = f"<service>Channel {title} created</service>"
                    is_service_message = True
                elif action_type == "MessageActionChatCreate":
                    title = action_dict.get("title", "this group")
                    text = f"<service>Group {title} created</service>"
                    is_service_message = True
                elif action_type == "MessageActionGroupCall":
                    if action_dict.get("duration"):
                        text = f"<service>Group call ended</service>"
                    else:
                        text = f"<service>Group call started</service>"
                    is_service_message = True
                elif action_type == "MessageActionChatEditTitle":
                    title = action_dict.get("title", "")
                    text = f"<service>Group name changed to: {title}</service>"
                    is_service_message = True
                else:
                    text = f"<service>Service message: {action_type}</service>"
                    is_service_message = True
            
            web_preview = await get_web_preview_data(message)
            
            if message.media:
                media_type = message_dict["media"]["_"]
                
                if download_media:
                    if not await media_exists(cursor, entity_id, id, media_type):
                        try:
                            media_file = await message.download_media(file=f"media/{entity_id}/")
                            if media_file:
                                media_hash = get_file_hash(media_file)
                        except Exception as e:
                            print(f"Error downloading media from message {id}: {e}")
                    else:
                        cursor.execute("SELECT media_file, media_hash FROM messages WHERE id = ? AND entity_id = ?", 
                                      (id, entity_id))
                        result = cursor.fetchone()
                        if result:
                            media_file, media_hash = result
            
            forwarded = str(message.fwd_from) if message.fwd_from else None
            from_id = str(message.from_id)
            views = message.views
            
            sender_name = None
            
            if message.sender:
                if hasattr(message.sender, 'first_name') and message.sender.first_name:
                    sender_name = message.sender.first_name
                    if hasattr(message.sender, 'last_name') and message.sender.last_name:
                        sender_name += f" {message.sender.last_name}"
                elif hasattr(message.sender, 'title'):
                    sender_name = message.sender.title
            
            if not sender_name:
                try:
                    channel_name = await get_channel_name_from_message(client, message)
                    if channel_name:
                        sender_name = channel_name
                    elif message.fwd_from:
                        if hasattr(message.fwd_from, 'from_name') and message.fwd_from.from_name:
                            sender_name = message.fwd_from.from_name
                        elif message.fwd_from.channel_id:
                            try:
                                fwd_channel = await client.get_entity(message.fwd_from.channel_id)
                                if hasattr(fwd_channel, 'title'):
                                    sender_name = f"{fwd_channel.title} (reenviado)"
                            except:
                                pass
                except Exception as e:
                    print(f"Error determinando remitente del mensaje {id}: {e}")
            
            reply_to_msg_id = message.reply_to_msg_id if message.reply_to_msg_id else None
            
            reactions_json = None
            if hasattr(message, 'reactions') and message.reactions:
                reactions_list = []
                for reaction in message.reactions.results:
                    emoji = get_emoji_string(reaction.reaction)
                    count = reaction.count
                    reactions_list.append({"emoji": emoji, "count": count})
                    cursor.execute("INSERT OR IGNORE INTO reactions VALUES (?, ?, ?, ?)",
                                  (int(id), int(entity_id), str(emoji), int(count)))
                reactions_json = json.dumps(reactions_list)
            
            cursor.execute("""
            INSERT OR IGNORE INTO messages 
            (id, entity_id, date, text, media_type, media_file, media_hash, forwarded, from_id, views, 
            sender_name, reply_to_msg_id, reactions, web_preview, extraction_time, is_service_message) 
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (int(id), int(entity_id), date, text, media_type, media_file, media_hash, forwarded, from_id, 
                 views if views is not None else 0, sender_name, 
                 int(reply_to_msg_id) if reply_to_msg_id is not None else None, 
                 reactions_json, web_preview, extraction_time, is_service_message))
            
            if reply_to_msg_id:
                cursor.execute("INSERT OR IGNORE INTO replies VALUES (?, ?, ?)",
                              (int(id), int(entity_id), int(reply_to_msg_id)))
            
            if message.buttons:
                for i, row in enumerate(message.buttons):
                    for j, button in enumerate(row):
                        cursor.execute("INSERT OR IGNORE INTO buttons VALUES (?, ?, ?, ?, ?, ?, ?)",
                                       (int(id), int(entity_id), int(i), int(j), str(button.text), 
                                        str(button.data) if button.data else None, 
                                        str(button.url) if button.url else None))
            
            if text and not is_service_message:
                soup = BeautifulSoup(text, "html.parser")
                for link in soup.find_all('a'):
                    cursor.execute("INSERT OR IGNORE INTO buttons VALUES (?, ?, ?, ?, ?, ?, ?)",
                                   (int(id), int(entity_id), 0, 0, str(link.text), None, str(link['href'])))
            
            conn.commit()
            
            print(f"Message {id} processed", end='\r')
        
        print(f"\nAll messages from {entity_name} have been processed.")
    except errors.FloodWaitError as e:
        print(f'A flood error occurred. Waiting {e.seconds} seconds before continuing.')
        await asyncio.sleep(e.seconds)
    except errors.ChannelPrivateError:
        print(f"Cannot access entity {entity_name} (ID: {entity_id}). It may be private or you may have been banned.")
    finally:
        conn.close()
    
    generate_html(db_name, sanitized_name, entity_id)

async def update_entity(client, entity_id, entity_name, entity, download_media=False):
    print(f"\nActualizando: {entity_name} (ID: {entity_id})")
    
    sanitized_name = sanitize_filename(f"{entity_id}_{entity_name}")
    db_name = f"{sanitized_name}.db"
    
    if not os.path.exists(db_name):
        print(f"No se encontró una base de datos existente para {entity_name}. Creando nuevo respaldo...")
        await process_entity(client, entity_id, entity_name, entity, download_media=download_media)
        return
    
    conn = sqlite3.connect(db_name)
    cursor = conn.cursor()
    
    cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='messages'")
    if not cursor.fetchone():
        print(f"La base de datos existe pero no tiene la estructura correcta. Creando nuevo respaldo...")
        conn.close()
        await process_entity(client, entity_id, entity_name, entity, download_media=download_media)
        return
    
    cursor.execute("SELECT sql FROM sqlite_master WHERE type='table' AND name='messages'")
    table_schema = cursor.fetchone()[0]
    if 'is_service_message' not in table_schema:
        print("Updating database schema to include service message information...")
        cursor.execute("ALTER TABLE messages ADD COLUMN is_service_message BOOLEAN DEFAULT 0")
        conn.commit()
    
    extraction_time = datetime.datetime.now(datetime.timezone.utc).isoformat()
    
    cursor.execute("SELECT MAX(id) FROM messages WHERE entity_id = ?", (entity_id,))
    result = cursor.fetchone()
    last_msg_id = result[0] if result[0] is not None else 0
    
    print(f"Último mensaje en la base de datos: {last_msg_id}")
    print("Recuperando mensajes más recientes...")
    
    new_messages_count = 0
    
    try:
        async for message in client.iter_messages(entity):
            if message.id <= last_msg_id:
                break  
                
            message_dict = message.to_dict()
            id = message_dict["id"]
            date = message_dict["date"].isoformat()
            text = message_dict.get("message", None)
            media_type = None
            media_file = None
            media_hash = None
            is_service_message = False
            
            if hasattr(message, 'action') and message.action:
                action_dict = message.action.to_dict()
                action_type = action_dict["_"]
                
                if action_type == "MessageActionChatAddUser":
                    user_ids = action_dict.get("users", [])
                    user_names = []
                    for user_id in user_ids:
                        try:
                            user = await client.get_entity(user_id)
                            if hasattr(user, "first_name") and user.first_name:
                                name = user.first_name
                                if hasattr(user, "last_name") and user.last_name:
                                    name += f" {user.last_name}"
                            else:
                                name = f"User {user_id}"
                            user_names.append(name)
                        except Exception as e:
                            print(f"Error getting user {user_id}: {str(e)}")
                            user_names.append(f"User {user_id}")
                    text = f"<service>{', '.join(filter(None, user_names))} joined the group</service>"
                    is_service_message = True
                elif action_type == "MessageActionChatDeleteUser":
                    user_id = action_dict.get("user_id")
                    try:
                        user = await client.get_entity(user_id)
                        if hasattr(user, "first_name") and user.first_name:
                            name = user.first_name
                            if hasattr(user, "last_name") and user.last_name:
                                name += f" {user.last_name}"
                        else:
                            name = f"User {user_id}"
                    except Exception as e:
                        print(f"Error getting user {user_id}: {str(e)}")
                        name = f"User {user_id}"
                    text = f"<service>{name} left the group</service>"
                    is_service_message = True
                elif action_type == "MessageActionChatJoinedByLink":
                    try:
                        if message.sender:
                            user_name = message.sender.first_name
                            if hasattr(message.sender, "last_name") and message.sender.last_name:
                                user_name += f" {message.sender.last_name}"
                        else:
                            user_name = "Someone"
                    except:
                        user_name = "Someone"
                    text = f"<service>{user_name} joined the group via invite link</service>"
                    is_service_message = True
                elif action_type == "MessageActionChannelCreate":
                    title = action_dict.get("title", "this channel")
                    text = f"<service>Channel {title} created</service>"
                    is_service_message = True
                elif action_type == "MessageActionChatCreate":
                    title = action_dict.get("title", "this group")
                    text = f"<service>Group {title} created</service>"
                    is_service_message = True
                elif action_type == "MessageActionGroupCall":
                    if action_dict.get("duration"):
                        text = f"<service>Group call ended</service>"
                    else:
                        text = f"<service>Group call started</service>"
                    is_service_message = True
                elif action_type == "MessageActionChatEditTitle":
                    title = action_dict.get("title", "")
                    text = f"<service>Group name changed to: {title}</service>"
                    is_service_message = True
                else:
                    text = f"<service>Service message: {action_type}</service>"
                    is_service_message = True
            
            web_preview = await get_web_preview_data(message)
            
            if message.media:
                media_type = message_dict["media"]["_"]
                
                if download_media:
                    if not await media_exists(cursor, entity_id, id, media_type):
                        try:
                            media_file = await message.download_media(file=f"media/{entity_id}/")
                            if media_file:
                                media_hash = get_file_hash(media_file)
                        except Exception as e:
                            print(f"Error downloading media from message {id}: {e}")
            
            forwarded = str(message.fwd_from) if message.fwd_from else None
            from_id = str(message.from_id)
            views = message.views
            
            sender_name = None
            
            if message.sender:
                if hasattr(message.sender, 'first_name') and message.sender.first_name:
                    sender_name = message.sender.first_name
                    if hasattr(message.sender, 'last_name') and message.sender.last_name:
                        sender_name += f" {message.sender.last_name}"
                elif hasattr(message.sender, 'title'):
                    sender_name = message.sender.title
            
            if not sender_name:
                try:
                    channel_name = await get_channel_name_from_message(client, message)
                    if channel_name:
                        sender_name = channel_name
                    elif message.fwd_from:
                        if hasattr(message.fwd_from, 'from_name') and message.fwd_from.from_name:
                            sender_name = message.fwd_from.from_name
                        elif message.fwd_from.channel_id:
                            try:
                                fwd_channel = await client.get_entity(message.fwd_from.channel_id)
                                if hasattr(fwd_channel, 'title'):
                                    sender_name = f"{fwd_channel.title} (reenviado)"
                            except:
                                pass
                except Exception as e:
                    print(f"Error determinando remitente del mensaje {id}: {e}")
            
            reply_to_msg_id = message.reply_to_msg_id if message.reply_to_msg_id else None
            
            reactions_json = None
            if hasattr(message, 'reactions') and message.reactions:
                reactions_list = []
                for reaction in message.reactions.results:
                    emoji = get_emoji_string(reaction.reaction)
                    count = reaction.count
                    reactions_list.append({"emoji": emoji, "count": count})
                    cursor.execute("INSERT OR IGNORE INTO reactions VALUES (?, ?, ?, ?)",
                                  (int(id), int(entity_id), str(emoji), int(count)))
                reactions_json = json.dumps(reactions_list)
            
            cursor.execute("""
            INSERT OR IGNORE INTO messages 
            (id, entity_id, date, text, media_type, media_file, media_hash, forwarded, from_id, views, 
            sender_name, reply_to_msg_id, reactions, web_preview, extraction_time, is_service_message) 
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (int(id), int(entity_id), date, text, media_type, media_file, media_hash, forwarded, from_id, 
                 views if views is not None else 0, sender_name, 
                 int(reply_to_msg_id) if reply_to_msg_id is not None else None, 
                 reactions_json, web_preview, extraction_time, is_service_message))
            
            if reply_to_msg_id:
                cursor.execute("INSERT OR REPLACE INTO replies VALUES (?, ?, ?)",
                              (id, entity_id, reply_to_msg_id))
            
            if message.buttons:
                for i, row in enumerate(message.buttons):
                    for j, button in enumerate(row):
                        cursor.execute("INSERT OR IGNORE INTO buttons VALUES (?, ?, ?, ?, ?, ?, ?)",
                                       (id, entity_id, i, j, button.text, button.data, button.url))
            
            if text and not is_service_message:
                soup = BeautifulSoup(text, "html.parser")
                for link in soup.find_all('a'):
                    cursor.execute("INSERT OR IGNORE INTO buttons VALUES (?, ?, ?, ?, ?, ?, ?)",
                                   (id, entity_id, 0, 0, link.text, None, link['href']))
            
            conn.commit()
            new_messages_count += 1
            print(f"Mensaje {id} procesado", end='\r')
        
        print(f"\nActualización completada. {new_messages_count} mensajes nuevos añadidos a {entity_name}.")
    except Exception as e:
        print(f"Error al actualizar mensajes: {e}")
    finally:
        conn.close()
    
    generate_html(db_name, sanitized_name, entity_id)

def generate_html(db_name, chat_name, entity_id=None):
    conn = sqlite3.connect(db_name)
    cursor = conn.cursor()
    
    entity_filter = ""
    params = ()
    
    if entity_id is not None:
        entity_filter = "WHERE m.entity_id = ?"
        params = (entity_id,)
    
    cursor.execute(f"""
    SELECT m.id, m.date, m.text, m.media_type, m.media_file, m.forwarded, m.from_id, m.views, 
           m.sender_name, m.reply_to_msg_id, m.reactions, m.entity_id, m.web_preview,
           GROUP_CONCAT(b.text || ',' || b.url, '|') as buttons,
           GROUP_CONCAT(r.emoji || ':' || r.count, ',') as reactions,
           m.is_service_message
    FROM messages m 
    LEFT JOIN buttons b ON m.id = b.message_id AND m.entity_id = b.entity_id
    LEFT JOIN reactions r ON m.id = r.message_id AND m.entity_id = r.entity_id
    {entity_filter}
    GROUP BY m.id, m.entity_id
    ORDER BY m.date DESC
    """, params)
    messages = cursor.fetchall()
    
    if entity_id is not None:
        date_groups = {}
        
        for message in messages:
            date_str = message[1]
            if date_str and 'T' in date_str:
                try:
                    msg_date = datetime.datetime.fromisoformat(date_str)
                    day_str = msg_date.strftime("%B %d, %Y")
                except (ValueError, AttributeError):
                    if 'T' in date_str:
                        day_str = date_str.split('T')[0]
                    else:
                        day_str = "Unknown Date"
            else:
                day_str = "Unknown Date"
            
            if day_str not in date_groups:
                date_groups[day_str] = []
            
            date_groups[day_str].append(message)
        
        grouped_messages = [(date, msgs) for date, msgs in date_groups.items()]
    else:
        grouped_messages = []
        for message in messages:
            date_str = message[1]
            if date_str and 'T' in date_str:
                day_str = date_str.split('T')[0]
            else:
                day_str = "Unknown Date"
            grouped_messages.append((day_str, [message]))
    
    conn.close()

    env = Environment(loader=FileSystemLoader('./'))
    template = env.get_template('template.html')
    
    output = template.render(
        chat_name=chat_name,
        grouped_messages=grouped_messages,
        entity_id=entity_id,
        os=os,
        get_url_from_forwarded=get_url_from_forwarded,
        json=json
    )
    
    with open(f"{chat_name}.html", "w", encoding='utf-8') as f:
        f.write(output)
    
    print(f"HTML file generated: {chat_name}.html")

if __name__ == "__main__":
    asyncio.run(main())
