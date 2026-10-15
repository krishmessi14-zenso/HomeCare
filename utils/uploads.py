import uuid
from pathlib import Path, PurePosixPath

from werkzeug.utils import secure_filename


IMAGE_SIGNATURES = {
    ".jpg": lambda data: data.startswith(b"\xff\xd8\xff"),
    ".jpeg": lambda data: data.startswith(b"\xff\xd8\xff"),
    ".png": lambda data: data.startswith(b"\x89PNG\r\n\x1a\n"),
    ".gif": lambda data: data.startswith((b"GIF87a", b"GIF89a")),
    ".webp": lambda data: data[:4] == b"RIFF" and data[8:12] == b"WEBP",
}


def save_service_image(upload, static_folder):
    filename = secure_filename(upload.filename or "")
    extension = Path(filename).suffix.lower()
    validator = IMAGE_SIGNATURES.get(extension)
    if not filename or validator is None:
        raise ValueError("Choose a JPG, PNG, GIF, or WebP image.")

    signature = upload.stream.read(12)
    upload.stream.seek(0)
    if not validator(signature):
        raise ValueError("The uploaded file does not match its image type.")

    relative = PurePosixPath("images", "uploads", f"{uuid.uuid4().hex}{extension}")
    destination = Path(static_folder).joinpath(*relative.parts)
    destination.parent.mkdir(parents=True, exist_ok=True)
    upload.save(destination)
    return relative.as_posix()


def delete_service_image(image_path, static_folder):
    relative = PurePosixPath(image_path or "")
    if len(relative.parts) != 3 or relative.parts[:2] != ("images", "uploads"):
        return
    path = Path(static_folder).joinpath(*relative.parts)
    try:
        path.unlink()
    except FileNotFoundError:
        pass