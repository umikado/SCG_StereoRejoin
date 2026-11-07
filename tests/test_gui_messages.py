"""GUI localization does not modify opaque source names or engine behavior."""
from pathlib import Path
import pytest
from scg_stereorejoin.gui_messages import _CATALOG, translate_message, format_gui_report
from scg_stereorejoin.pairing import NamedFile, SuffixPattern, PatternError
from scg_stereorejoin.rejoin import BatchReport, JoinedItem, RefusedItem, format_report

@pytest.mark.parametrize('language', ['zh', 'zh-CN', 'ja'])
@pytest.mark.parametrize('template,zh,ja', _CATALOG)
def test_entire_catalog(language, template, zh, ja):
    values = tuple(str(n + 17) for n in range(8))
    raw = template.format(*values)
    expected = (zh if language.startswith('zh') else ja).format(*values)
    assert translate_message(raw, language) == expected
    assert translate_message(raw + '\n', language) == expected + '\n'
    assert translate_message(raw, 'en') == raw

@pytest.mark.parametrize('language', ['zh-CN', 'ja'])
def test_structured_reports_keep_paths(language):
    left = Path('/資料/warning: left file.L.wav')
    right = Path('/資料/joined + right file.R.wav')
    output = Path('/資料/summary warning: joined.wav')
    report = BatchReport(
        joined=[JoinedItem(left, right, output, 1234, 48000, 24, '24-bit PCM', 'RIFF', 99, 0, 0,
                           ['padded the left file with 7 silent frames'], ['bext', 'iXML'], False)],
        unpaired=[NamedFile(left, 'missing right partner')],
        unmatched=[NamedFile(right, 'name does not match an L/R pattern')],
        refused=[RefusedItem(left, right, 'audio data is truncated')],
        errors=[f'path not found: {output}'],
    )
    result = format_gui_report(report, language, verbose=True)
    for value in [str(left), str(right), str(output), '48000', '1234', '99', '24-bit PCM', 'RIFF', 'bext, iXML']:
        assert value in result
    assert 'missing right partner' not in result
    assert 'audio data is truncated' not in result
    assert 'would join' not in result
    assert format_gui_report(report, 'en', verbose=True) == format_report(report, verbose=True)
    assert '1234' not in format_gui_report(report, language, quiet=True, verbose=True)

@pytest.mark.parametrize('language', ['zh-CN', 'ja'])
def test_opaque_warning_and_progress_fields(language):
    name = 'warning: left file; joined + right file_日本語.wav'
    for raw in [f'joining {name} + {name}', f'wrote /音/{name}', f'would write /音/{name}',
                f'left source {name}: selected internal channel 2 for output LEFT (the other channel is exactly silent)',
                f'/音/{name}: audio data is truncated', f'/音/{name} changed while it was being read']:
        result = translate_message(raw, language)
        assert name in result
        assert result != raw
        assert '原文' not in result

@pytest.mark.parametrize('language', ['zh-CN', 'ja'])
def test_pattern_validation_and_nested_location(language):
    for spec in ['', 'warning left file 日本語', '/Right', 'warning/warning']:
        with pytest.raises(PatternError) as caught:
            SuffixPattern.parse(spec)
        raw = str(caught.value)
        result = translate_message(raw, language)
        assert repr(spec) in result
        assert result != raw
        assert '原文' not in result
        located = '/資料/warning: left file.txt:17: ' + raw
        assert translate_message(located, language).startswith('/資料/warning: left file.txt:17: ')

@pytest.mark.parametrize('language', ['zh-CN', 'ja'])
def test_nested_and_composite_reasons(language):
    reasons = [
        'sample rate mismatch (44100 Hz vs 48000 Hz); this tool does not resample; bit depth mismatch (16 vs 24); this tool does not convert bit depth; valid-bit mismatch (16 vs 24)',
        'left file has 3 channels; expected mono or single-active-channel stereo; right file has 4 channels; expected mono or single-active-channel stereo',
        '/資料/left file.wav: 1 channels, expected 2; 32 frames, expected 64; 44100 Hz, expected 48000; 16 bits, expected 24',
        'output failed verification: /資料/warning.wav: /資料/warning.wav: audio data is truncated',
        'warning left source warning: left file.wav: selected internal channel 1 for output LEFT (both channels are silent)',
        'error: large-file container must be rf64 or bw64\n',
    ]
    for reason in reasons:
        result = translate_message(reason, language)
        assert result != reason
        for residual in ['expected', 'mismatch', 'truncated', 'channels;', 'both channels are silent', 'must be']:
            assert residual not in result
        assert '原文' not in result

@pytest.mark.parametrize('language', ['zh-CN', 'ja'])
def test_unknown_os_error_is_verbatim_diagnostic(language):
    raw = "[Errno 13] Permission denied: '/資料/left file warning.wav'"
    result = translate_message(raw, language)
    assert result.endswith(raw)
    assert '原文' in result
    assert translate_message(raw, 'en') == raw
