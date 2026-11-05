import xml.etree.ElementTree as ET

from scg_stereorejoin.ixml import mirror_channel_name, update_ixml
from tests.support import demo_ixml


def local(tag: str) -> str:
    if tag.startswith("{"):
        tag = tag.split("}", 1)[1]
    return tag.upper()


def texts(blob: bytes) -> dict[str, list[str]]:
    payload = blob.split(b"?>", 1)[-1]
    root = ET.fromstring(payload)
    found: dict[str, list[str]] = {}
    for element in root.iter():
        if not isinstance(element.tag, str):
            continue
        if element.text and element.text.strip():
            found.setdefault(local(element.tag), []).append(element.text.strip())
    return found


def test_track_list_becomes_stereo_and_preserves_the_rest():
    left = demo_ixml(name="Dialogue.L", function="LEFT", file_index="1")
    right = demo_ixml(name="Dialogue.R", function="RIGHT", file_index="2", project="ignored")
    right = right.replace(b"<NOTES>boom</NOTES>", b"<NOTES>room</NOTES>")
    result = update_ixml(left, right)
    assert result.changed
    body = texts(result.data)
    assert body["PROJECT"] == ["Tom & Jerry"]
    assert body["SCENE"] == ["01A"]
    assert body["TAKE"] == ["3"]
    assert body["STUDIO"] == ["Nightshift"]
    assert body["FAMILY_NAME"] == ["Dialogue"]
    assert body["FAMILY_UID"] == ["FAMILY-KEEP"]
    assert body["TIMESTAMP_SAMPLES_SINCE_MIDNIGHT_LO"] == ["230400000"]
    assert body["TIMESTAMP_SAMPLES_SINCE_MIDNIGHT_HI"] == ["0"]
    assert body["AUDIO_BIT_DEPTH"] == ["24"]
    assert body["TRACK_COUNT"] == ["2"]
    assert body["TOTAL_FILES"] == ["1"]
    assert body["FILE_SET_INDEX"] == ["1"]
    assert body["CHANNEL_INDEX"] == ["1", "2"]
    assert body["INTERLEAVE_INDEX"] == ["1", "2"]
    assert body["FUNCTION"] == ["LEFT", "RIGHT"]
    assert body["NAME"] == ["Dialogue.L", "Dialogue.R"]
    assert body["NOTES"] == ["boom", "room"]
    assert b"keep me" in result.data
    assert b"ns0" not in result.data


def test_file_set_above_two_is_left_alone():
    left = demo_ixml(total_files="5", file_index="4")
    result = update_ixml(left, None)
    body = texts(result.data)
    assert body["TOTAL_FILES"] == ["5"]
    assert body["FILE_SET_INDEX"] == ["4"]
    assert body["TRACK_COUNT"] == ["2"]


def test_missing_right_ixml_mirrors_the_left_name():
    result = update_ixml(demo_ixml(name="Hat.L"), None)
    assert texts(result.data)["NAME"] == ["Hat.L", "Hat.R"]
    assert texts(result.data)["FUNCTION"] == ["LEFT", "RIGHT"]


def test_document_without_a_track_list_is_copied_byte_for_byte():
    original = b'<?xml version="1.0" encoding="UTF-8"?><BWFXML><PROJECT>Keep</PROJECT></BWFXML>'
    result = update_ixml(original, None)
    assert result.changed is False
    assert result.data == original


def test_invalid_ixml_is_copied_with_a_warning():
    original = b"<not xml"
    result = update_ixml(original, None)
    assert result.data == original
    assert result.warnings
    assert result.changed is False


def test_mirror_channel_name_respects_case():
    assert mirror_channel_name("Dialogue.L") == "Dialogue.R"
    assert mirror_channel_name("dialogue.left") == "dialogue.right"
    assert mirror_channel_name("HAT_LEFT") == "HAT_RIGHT"
    assert mirror_channel_name("Room") == "Room"
