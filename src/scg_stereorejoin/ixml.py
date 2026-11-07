"""Update an iXML chunk so a rejoined file describes two interleaved channels.

The left file's document is the base. Project, scene, take, speed, and the
BWF timestamp fields are left alone. ``TRACK_LIST`` becomes two tracks
(left, then right). A ``FILE_SET`` whose ``TOTAL_FILES`` is exactly 2 is
collapsed to one file, because that is the split pair we just joined.
"""

from __future__ import annotations

import copy
import re
import xml.etree.ElementTree as ET
from dataclasses import dataclass

_DECLARATION = re.compile(r"^\s*<\?xml[^?]*\?>", re.IGNORECASE)
_NAME_MIRRORS: tuple[tuple[str, str], ...] = (
    (".Left", ".Right"),
    ("_Left", "_Right"),
    ("-Left", "-Right"),
    (" Left", " Right"),
    (".L", ".R"),
    ("_L", "_R"),
    ("-L", "-R"),
    (" L", " R"),
    (".1", ".2"),
    ("_1", "_2"),
    ("-1", "-2"),
    ("Left", "Right"),
    ("L", "R"),
)


@dataclass
class IxmlUpdate:
    data: bytes
    changed: bool
    warnings: list[str]


class _CommentBuilder(ET.TreeBuilder):
    def comment(self, data: str) -> None:
        self.start(ET.Comment, {})
        self.data(data)
        self.end(ET.Comment)


def update_ixml(left_blob: bytes, right_blob: bytes | None = None, *,
                left_channel: int | None = None, right_channel: int | None = None,
                base_from_right: bool = False) -> IxmlUpdate:
    """Return new iXML bytes. Invalid XML is copied through with a warning.

    Optional zero-based channel indexes select physical stereo source tracks
    instead of the legacy mono FUNCTION preference. ``base_from_right`` is
    used when only the right stereo source has iXML: retain its document but
    do not mislabel its silent channel as metadata for the absent left track.
    """
    warnings: list[str] = []
    try:
        left_text = _decode(left_blob)
    except UnicodeError:
        warnings.append("iXML on the left file is not valid text; copied it unchanged")
        return IxmlUpdate(left_blob, False, warnings)
    try:
        root, _decl = _parse(left_text)
    except ET.ParseError:
        warnings.append("iXML on the left file is not valid XML; copied it unchanged")
        return IxmlUpdate(left_blob, False, warnings)

    right_root: ET.Element | None = None
    if right_blob:
        try:
            right_root, _ = _parse(_decode(right_blob))
        except (UnicodeError, ET.ParseError):
            warnings.append(
                "iXML on the right file could not be parsed; the right channel name was taken from the left track"
            )

    changed = False
    track_list = _find(root, "TRACK_LIST")
    if track_list is not None:
        _rewrite_tracks(track_list, right_root, warnings, left_channel, right_channel, base_from_right)
        changed = True
    file_set = _find(root, "FILE_SET")
    if file_set is not None and _collapse_pair_file_set(file_set):
        changed = True
    if not changed:
        return IxmlUpdate(left_blob, False, warnings)
    return IxmlUpdate(_serialize(root), True, warnings)


def mirror_channel_name(name: str) -> str:
    """Turn a left-looking track name into the matching right name, when obvious."""
    for src, dst in _NAME_MIRRORS:
        if name.casefold().endswith(src.casefold()):
            original = name[-len(src) :]
            return name[: -len(src)] + _match_case(original, dst)
    return name


def _rewrite_tracks(track_list: ET.Element, right_root: ET.Element | None, warnings: list[str],
                    left_channel: int | None = None, right_channel: int | None = None,
                    base_from_right: bool = False) -> None:
    existing = _children(track_list, "TRACK")
    for track in existing:
        track_list.remove(track)
    left_track = _selected_track(existing, left_channel, "LEFT", warnings)
    if base_from_right:
        left_track = _new_element(track_list, "TRACK")
        _set_child(left_track, "NAME", "Left")
    if left_track is None:
        left_track = existing[0] if existing else _new_element(track_list, "TRACK")
        if not existing:
            warnings.append("iXML track list had no TRACK entry; added Left and Right")

    right_track: ET.Element | None = None
    if base_from_right:
        right_track = _selected_track(existing, right_channel, "RIGHT", warnings)
    if right_root is not None:
        right_list = _find(right_root, "TRACK_LIST")
        if right_list is not None:
            right_tracks = _children(right_list, "TRACK")
            chosen = _selected_track(right_tracks, right_channel, "RIGHT", warnings)
            if chosen is None and right_tracks:
                chosen = right_tracks[0]
            if chosen is not None:
                right_track = copy.deepcopy(chosen)
    if right_track is None and len(existing) >= 2 and left_channel is None and not base_from_right:
        spare = next((track for track in existing if track is not left_track), None)
        if spare is not None:
            right_track = spare
    cloned = False
    if right_track is None:
        right_track = copy.deepcopy(left_track)
        cloned = True
    _set_track(left_track, index=1, function="LEFT")
    _set_track(right_track, index=2, function="RIGHT")
    if cloned:
        _retitle_clone(right_track)

    counts = _children(track_list, "TRACK_COUNT")
    if counts:
        counts[0].text = "2"
        for extra in counts[1:]:
            track_list.remove(extra)
    else:
        track_list.insert(0, _new_element(track_list, "TRACK_COUNT", "2"))
    track_list.append(left_track)
    track_list.append(right_track)


def _selected_track(tracks: list[ET.Element], channel: int | None, function: str,
                    warnings: list[str]) -> ET.Element | None:
    if channel is None:
        return _prefer(tracks, function)
    # INTERLEAVE_INDEX identifies the physical sample channel; CHANNEL_INDEX
    # can instead identify an original recorder track in a split file.
    for field in ("INTERLEAVE_INDEX", "CHANNEL_INDEX"):
        indexed = [track for track in tracks if _children(track, field)]
        if indexed:
            matches = [track for track in indexed if
                       (_children(track, field)[0].text or "").strip() == str(channel + 1)]
            if len(matches) == 1:
                return matches[0]
            break
    else:
        if len(tracks) == 2:
            return tracks[channel]
    warnings.append(f"iXML metadata for selected internal channel {channel + 1} is unavailable; used a generic {function.title()} track")
    track = ET.Element("TRACK") if not tracks else _new_element(tracks[0], "TRACK")
    _set_child(track, "NAME", function.title())
    return track


def _retitle_clone(track: ET.Element) -> None:
    names = _children(track, "NAME")
    if not names:
        return
    text = names[0].text or ""
    if text:
        names[0].text = mirror_channel_name(text)


def _collapse_pair_file_set(file_set: ET.Element) -> bool:
    totals = _children(file_set, "TOTAL_FILES")
    if not totals:
        return False
    if (totals[0].text or "").strip() != "2":
        return False
    totals[0].text = "1"
    indexes = _children(file_set, "FILE_SET_INDEX")
    if indexes:
        indexes[0].text = "1"
    return True


def _set_track(track: ET.Element, *, index: int, function: str) -> None:
    _set_child(track, "CHANNEL_INDEX", str(index))
    _set_child(track, "INTERLEAVE_INDEX", str(index))
    _set_child(track, "FUNCTION", function)


def _prefer(tracks: list[ET.Element], function: str) -> ET.Element | None:
    function = function.upper()
    for track in tracks:
        values = _children(track, "FUNCTION")
        if values and (values[0].text or "").strip().upper() == function:
            return track
    return None


def _set_child(parent: ET.Element, name: str, value: str) -> None:
    found = _children(parent, name)
    if found:
        found[0].text = value
        return
    parent.append(_new_element(parent, name, value))


def _new_element(parent: ET.Element, name: str, text: str | None = None) -> ET.Element:
    element = ET.Element(f"{_namespace(parent)}{name}")
    if text is not None:
        element.text = text
    return element


def _children(parent: ET.Element, name: str) -> list[ET.Element]:
    wanted = name.upper()
    return [child for child in list(parent) if isinstance(child.tag, str) and _local(child.tag) == wanted]


def _find(root: ET.Element, name: str) -> ET.Element | None:
    wanted = name.upper()
    for element in root.iter():
        if isinstance(element.tag, str) and _local(element.tag) == wanted:
            return element
    return None


def _local(tag: str) -> str:
    if tag.startswith("{"):
        tag = tag.split("}", 1)[1]
    return tag.upper()


def _namespace(element: ET.Element) -> str:
    tag = element.tag if isinstance(element.tag, str) else ""
    if tag.startswith("{"):
        return tag.split("}", 1)[0] + "}"
    return ""


def _decode(blob: bytes) -> str:
    data = blob
    if data.startswith(b"\xff\xfe") or data.startswith(b"\xfe\xff"):
        return data.decode("utf-16")
    if data.startswith(b"\xef\xbb\xbf"):
        data = data[3:]
    if data.endswith(b"\x00"):
        data = data[:-1]
    return data.decode("utf-8")


def _parse(text: str) -> tuple[ET.Element, str | None]:
    declaration: str | None = None
    match = _DECLARATION.match(text)
    payload = text
    if match:
        declaration = match.group(0).strip()
        payload = text[match.end() :]
    # A wrapper keeps a comment or whitespace before the real root from
    # becoming the document element. Only the real root is serialized back.
    parser = ET.XMLParser(target=_CommentBuilder())
    parser.feed("<scg-ixml-root>")
    parser.feed(payload)
    parser.feed("</scg-ixml-root>")
    wrapper = parser.close()
    elements = [child for child in list(wrapper) if isinstance(child.tag, str)]
    if len(elements) != 1:
        raise ET.ParseError("iXML document must have one root element")
    return elements[0], declaration


def _serialize(root: ET.Element) -> bytes:
    if isinstance(root.tag, str) and root.tag.startswith("{"):
        uri = root.tag[1:].split("}", 1)[0]
        ET.register_namespace("", uri)
    ET.indent(root, space="  ")
    body = ET.tostring(root, encoding="utf-8", xml_declaration=False, short_empty_elements=False)
    header = b'<?xml version="1.0" encoding="UTF-8"?>\n'
    if not body.endswith(b"\n"):
        body += b"\n"
    return header + body


def _match_case(original: str, replacement: str) -> str:
    if original.isupper():
        return replacement.upper()
    if original.islower():
        return replacement.lower()
    if original[:1].isupper():
        return replacement[:1].upper() + replacement[1:]
    return replacement
