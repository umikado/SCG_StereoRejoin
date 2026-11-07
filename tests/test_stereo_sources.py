"""Single-active-channel stereo sources retain raw samples and metadata."""
import hashlib
import io
import struct
import xml.etree.ElementTree as ET

import pytest

from scg_stereorejoin import rejoin, wav
from tests.support import join_folder, reference_interleave


def source(path, encoding, audio, channels=2, xml=None):
    fmt = wav.make_fmt(encoding, 48000, channels)
    chunks = wav.build_wav_chunks(fmt, frames=len(audio) // fmt.block_align,
                                  after_fmt=[wav.Chunk(b'iXML', xml)] if xml else [])
    wav.write_wav(path, fmt=fmt, audio=audio, chunks=chunks)
    return wav.read_wav(path)


@pytest.mark.parametrize('encoding,width', [('pcm16', 2), ('pcm24', 3), ('pcm32', 4),
                                            ('float32', 4), ('float64', 8)])
@pytest.mark.parametrize('ext', ['', 'ext-'])
@pytest.mark.parametrize('active', [0, 1])
def test_exact_supported_carriers(tmp_path, encoding, width, ext, active):
    # Arbitrary bit patterns include tiny float values, not a level threshold.
    a = b''.join(i.to_bytes(width, 'little') for i in [1, 0, 5, 0, 7])
    b = b''.join(i.to_bytes(width, 'little') for i in [8, 2, 0, 6, 0])
    silence = bytes(len(a))
    source(tmp_path / 'Take.L.wav', ext + encoding,
           reference_interleave(a, silence, width) if active == 0 else reference_interleave(silence, a, width))
    source(tmp_path / 'Take.R.wav', ext + encoding,
           reference_interleave(b, silence, width) if active == 0 else reference_interleave(silence, b, width))
    report = join_folder(tmp_path, tmp_path / 'out', chunk_frames=2)
    assert report.ok, report.refused
    info = wav.read_wav(report.joined[0].output)
    assert wav.read_audio(info.path, info) == reference_interleave(a, b, width)
    assert sum(f'selected internal channel {active + 1}' in w for w in report.joined[0].warnings) == 2


@pytest.mark.parametrize('encoding,code', [('float32', 'f'), ('float64', 'd')])
def test_float_signed_silence_and_nan(tmp_path, encoding, code):
    zeros = struct.pack('<' + code * 3, -0.0, 0.0, -0.0)
    audio = struct.pack('<' + code * 3, float('nan'), float('inf'), 0.25)
    width = len(zeros) // 3
    source(tmp_path / 'Take.L.wav', encoding, reference_interleave(zeros, audio, width))
    source(tmp_path / 'Take.R.wav', encoding, reference_interleave(zeros, zeros, width))
    report = join_folder(tmp_path, tmp_path / 'out', chunk_frames=1)
    assert report.ok
    info = wav.read_wav(report.joined[0].output)
    assert wav.read_audio(info.path, info) == reference_interleave(audio, zeros, width)
    assert any('both channels are silent' in w for w in report.joined[0].warnings)


def test_disjoint_activity_refuses_even_dry_run(tmp_path):
    source(tmp_path / 'Take.L.wav', 'pcm16', struct.pack('<hhhh', 1, 0, 0, 1))
    source(tmp_path / 'Take.R.wav', 'pcm16', bytes(8))
    report = join_folder(tmp_path, tmp_path / 'out', dry_run=True, chunk_frames=1)
    assert not report.joined
    assert 'both stereo channels' in report.refused[0].reason
    assert not (tmp_path / 'out').exists()


def test_mixed_mono_and_stereo_padding(tmp_path):
    source(tmp_path / 'Take.L.wav', 'pcm24', b'\x01\0\0', channels=1)
    source(tmp_path / 'Take.R.wav', 'pcm24', b'\0\0\0\x02\0\0' * 2)
    report = join_folder(tmp_path, tmp_path / 'out', pad=True, chunk_frames=1)
    assert report.ok
    info = wav.read_wav(report.joined[0].output)
    assert wav.read_audio(info.path, info) == b'\x01\0\0\x02\0\0\0\0\0\x02\0\0'


def test_stream_source_view_hashes_both_channels(tmp_path):
    raw = struct.pack('<hhhh', 0, 7, 0, 8)
    info = source(tmp_path / 'L.wav', 'pcm16', raw)
    out = wav.write_interleaved_wav(tmp_path / 'out.wav', chunks=wav.build_wav_chunks(info.fmt),
        sample_width=2, left_path=info.path, right_path=info.path,
        left_offset=info.data_offset, right_offset=info.data_offset,
        left_frames=2, right_frames=2, left_channels=2, right_channels=2,
        left_channel=1, right_channel=1, chunk_frames=1)
    assert out.left.audio_bytes == len(raw)
    assert out.left.audio_sha256 == hashlib.sha256(raw).hexdigest()


def test_scan_uses_bounded_reads(tmp_path):
    raw = struct.pack('<hh', 0, 1) * 100
    info = source(tmp_path / 'L.wav', 'pcm16', raw)
    class Bounded(io.BytesIO):
        def read(self, count=-1):
            assert 0 <= count <= 12
            return super().read(count)
    handle = Bounded(info.path.read_bytes())
    channel, silent, digest = wav.scan_stereo_channel(handle, info, preferred=0, chunk_frames=3)
    assert (channel, silent) == (1, False)
    assert digest == hashlib.sha256(raw).hexdigest()


def test_scan_change_cannot_be_accepted(tmp_path, monkeypatch):
    raw = struct.pack('<hh', 0, 3) * 2
    left = source(tmp_path / 'Take.L.wav', 'pcm16', raw)
    source(tmp_path / 'Take.R.wav', 'pcm16', raw)
    original = rejoin.scan_stereo_channel
    def changed(handle, info, **kwargs):
        if info.path == left.path:
            with info.path.open('r+b') as edit:
                edit.seek(info.data_offset)
                edit.write(struct.pack('<hh', 9, 0) * 2)
        return original(handle, info, **kwargs)
    monkeypatch.setattr(rejoin, 'scan_stereo_channel', changed)
    report = join_folder(tmp_path, tmp_path / 'out')
    assert not report.joined
    assert 'changed while' in report.refused[0].reason
    assert not (tmp_path / 'out').exists()


def metadata(first, second):
    return (f'<BWFXML><TRACK_LIST><TRACK_COUNT>2</TRACK_COUNT>'
            f'<TRACK><INTERLEAVE_INDEX>2</INTERLEAVE_INDEX><FUNCTION>RIGHT</FUNCTION><NAME>{second}</NAME></TRACK>'
            f'<TRACK><INTERLEAVE_INDEX>1</INTERLEAVE_INDEX><FUNCTION>LEFT</FUNCTION><NAME>{first}</NAME></TRACK>'
            '</TRACK_LIST></BWFXML>').encode()


def test_metadata_follows_selected_channel_not_function(tmp_path):
    source(tmp_path / 'Take.L.wav', 'pcm16', struct.pack('<hh', 0, 5), xml=metadata('silent L', 'actual L'))
    source(tmp_path / 'Take.R.wav', 'pcm16', struct.pack('<hh', 6, 0), xml=metadata('actual R', 'silent R'))
    report = join_folder(tmp_path, tmp_path / 'out')
    assert report.ok
    root = ET.fromstring(wav.read_wav(report.joined[0].output).chunk(b'iXML').data)
    assert [t.findtext('NAME') for t in root.findall('./TRACK_LIST/TRACK')] == ['actual L', 'actual R']
    assert [t.findtext('FUNCTION') for t in root.findall('./TRACK_LIST/TRACK')] == ['LEFT', 'RIGHT']


def test_right_only_stereo_metadata_does_not_label_left_with_silent_track(tmp_path):
    source(tmp_path / 'Take.L.wav', 'pcm16', struct.pack('<hh', 0, 5))
    source(tmp_path / 'Take.R.wav', 'pcm16', struct.pack('<hh', 6, 0), xml=metadata('actual R', 'silent R'))
    report = join_folder(tmp_path, tmp_path / 'out')
    assert report.ok
    root = ET.fromstring(wav.read_wav(report.joined[0].output).chunk(b'iXML').data)
    assert [t.findtext('NAME') for t in root.findall('./TRACK_LIST/TRACK')] == ['Left', 'actual R']
