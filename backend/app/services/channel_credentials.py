"""Shared channel secret encryption. No fallback to signing keys or plaintext."""
from cryptography.fernet import Fernet, InvalidToken
from fastapi import HTTPException
from app.config import settings


def cipher():
    try:
        return Fernet(getattr(settings, 'CHANNEL_ENCRYPTION_KEY', '').encode())
    except (ValueError, TypeError):
        raise HTTPException(503, 'Channel credential encryption is not configured')


def encrypt(value):
    return cipher().encrypt(value.encode()).decode()


def decrypt(value):
    try:
        return cipher().decrypt(value.encode()).decode()
    except InvalidToken:
        raise HTTPException(503, 'Channel credentials cannot be decrypted; reconnect the account')
