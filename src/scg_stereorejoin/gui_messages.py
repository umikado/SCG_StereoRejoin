"""Presentation-only translations; audio engine strings remain canonical English.

Only entire known templates are translated. Captured user data is opaque. Reports
must use the structured formatter, never parse CLI report lines. OS/library
exceptions not in the catalog retain their exact technical diagnostic.
"""
from __future__ import annotations

import re
from .rejoin import BatchReport, format_report

# Each placeholder is an opaque value, never a target for word replacement.
_CATALOG = [
('iXML document must have one root element', 'iXML 文档必须只有一个根元素', 'iXML 文書にはルート要素が 1 つ必要です'),
('could not create a trash directory', '无法创建废纸篓目录', 'ゴミ箱用のフォルダを作成できませんでした'),
('Working…', '正在处理…', '処理中…'),
('no WAV files found', '未找到 WAV 文件', 'WAV ファイルが見つかりません'),
('large-file container must be rf64 or bw64', '大文件容器必须为 rf64 或 bw64', '大容量ファイルのコンテナは rf64 または bw64 にしてください'),
('left and right paths are the same file', '左右路径指向同一个文件', '左右のパスが同じファイルを指しています'),
('left file has no bext chunk; copied bext from the right file', '左侧文件没有 bext 块；已复制右侧文件的 bext', '左側ファイルに bext チャンクがないため、右側からコピーしました'),
('no bext chunk; a DAW cannot re-spot this file to a BWF timestamp', '没有 bext 块；DAW 无法根据 BWF 时间戳将此文件定位回原位置', 'bext チャンクがないため、DAW で BWF タイムスタンプに基づく元の位置への配置はできません'),
("left file has no iXML chunk; updated the right file's iXML instead", '左侧文件没有 iXML 块；已改为更新右侧文件的 iXML', '左側ファイルに iXML チャンクがないため、右側の iXML を更新しました'),
('iXML on the left file is not valid text; copied it unchanged', '左侧文件的 iXML 不是有效文本；已原样复制', '左側ファイルの iXML が有効なテキストではないため、そのままコピーしました'),
('iXML on the left file is not valid XML; copied it unchanged', '左侧文件的 iXML 不是有效 XML；已原样复制', '左側ファイルの iXML が有効な XML ではないため、そのままコピーしました'),
('iXML on the right file could not be parsed; the right channel name was taken from the left track', '无法解析右侧文件的 iXML；已根据左侧轨道确定右声道名称', '右側ファイルの iXML を解析できないため、左側トラックから右チャンネル名を取得しました'),
('iXML track list had no TRACK entry; added Left and Right', 'iXML 轨道列表没有 TRACK 条目；已添加 Left 和 Right', 'iXML のトラック一覧に TRACK がないため、Left と Right を追加しました'),
('name does not match an L/R pattern', '文件名不匹配任何 L/R 配对规则', 'ファイル名が L/R のペアリング規則に一致しません'),
('missing right partner', '缺少配对的右侧文件', 'ペアとなる右側ファイルがありません'),
('missing left partner', '缺少配对的左侧文件', 'ペアとなる左側ファイルがありません'),
('no pairing patterns are configured', '尚未配置配对规则', 'ペアリング規則が設定されていません'),
('path not found: {0}', '路径不存在：{0}', 'パスが見つかりません：{0}'),
('not a file or directory: {0}', '不是文件或目录：{0}', 'ファイルまたはフォルダではありません：{0}'),
('not a WAV file: {0}', '不是 WAV 文件：{0}', 'WAV ファイルではありません：{0}'),
('joining {0}', '正在合并 {0}', '結合中：{0}'),
('would write {0}', '预演：将写入 {0}', '試行：書き込み予定 {0}'),
('wrote {0}', '已写入 {0}', '書き込み完了：{0}'),
('output path {0} collides with input {1}', '输出路径 {0} 与输入文件 {1} 冲突', '出力パス {0} が入力ファイル {1} と競合します'),
('output path {0} collides with {1}', '输出路径 {0} 与 {1} 冲突', '出力パス {0} が {1} と競合します'),
('output path {0} is the same as a source file', '输出路径 {0} 与源文件相同', '出力パス {0} が元ファイルと同じです'),
('output already exists: {0} (pass --overwrite to replace it)', '输出文件已存在：{0}（启用覆盖或使用 --overwrite 可替换）', '出力ファイルが既に存在します：{0}（上書きを有効にするか --overwrite を指定すると置き換えます）'),
('could not create a temporary file in {0}', '无法在 {0} 中创建临时文件', '{0} に一時ファイルを作成できませんでした'),
('{0} changed while it was being read', '读取期间文件发生变化：{0}', '読み取り中にファイルが変更されました：{0}'),
('skipped deleting sources: output {0} no longer names the file this run published', '已跳过删除源文件：输出路径 {0} 已不再指向本次写入的文件', '元ファイルの削除を省略しました：出力パス {0} は今回書き込んだファイルを指していません'),
('skipped deleting {0}: file changed after it was read', '已跳过删除 {0}：读取后文件发生变化', '{0} の削除を省略しました：読み取り後にファイルが変更されています'),
('skipped deleting {0}: quarantined changed file at {1}', '已跳过删除 {0}：发生变化的文件已隔离到 {1}', '{0} の削除を省略しました：変更されたファイルを {1} に隔離しました'),
('skipped deleting {0}: left changed file at {1} ({2})', '已跳过删除 {0}：发生变化的文件保留在 {1}（系统诊断：{2}）', '{0} の削除を省略しました：変更されたファイルを {1} に残しました（システム診断：{2}）'),
('skipped deleting {0}: {1}', '已跳过删除 {0}（系统诊断：{1}）', '{0} の削除を省略しました（システム診断：{1}）'),
('moved {0} to {1}', '已将 {0} 移动到 {1}', '{0} を {1} に移動しました'),
('empty pattern {0}', '配对规则为空：{0}', 'ペアリング規則が空です：{0}'),
('pattern {0} must look like .L/.R', '配对规则 {0} 必须使用 .L/.R 这样的格式', 'ペアリング規則 {0} は .L/.R のような形式にしてください'),
('pattern {0} needs both a left and a right suffix', '配对规则 {0} 必须同时包含左右后缀', 'ペアリング規則 {0} には左右両方の接尾辞が必要です'),
('pattern {0} uses the same suffix for both sides', '配对规则 {0} 的左右后缀相同', 'ペアリング規則 {0} の左右の接尾辞が同じです'),
('cannot read patterns file {0}: {1}', '无法读取配对规则文件 {0}（系统诊断：{1}）', 'ペアリング規則ファイル {0} を読み取れません（システム診断：{1}）'),
('more than one file claims this stem ({0})', '多个文件对应同一主文件名（{0}）', '同じベース名に複数のファイルが対応しています（{0}）'),
('sample rate mismatch ({0} Hz vs {1} Hz); this tool does not resample', '采样率不一致（{0} Hz 与 {1} Hz）；本工具不进行重采样', 'サンプルレートが一致しません（{0} Hz と {1} Hz）。このツールはリサンプリングを行いません'),
('bit depth mismatch ({0} vs {1}); this tool does not convert bit depth', '位深不一致（{0} 与 {1}）；本工具不转换位深', 'ビット深度が一致しません（{0} と {1}）。このツールはビット深度を変換しません'),
('valid-bit mismatch ({0} vs {1})', '有效位数不一致（{0} 与 {1}）', '有効ビット数が一致しません（{0} と {1}）'),
('sample format mismatch ({0} vs {1}); this tool does not convert sample format', '采样格式不一致（{0} 与 {1}）；本工具不转换采样格式', 'サンプル形式が一致しません（{0} と {1}）。このツールはサンプル形式を変換しません'),
('block align does not match the sample width and channel count ({0} vs {1}, {2} vs {3})', '块对齐值与采样宽度及声道数不符（{0} 与 {1}，{2} 与 {3}）', 'ブロックアラインメントがサンプル幅とチャンネル数に一致しません（{0} と {1}、{2} と {3}）'),
('audio data size is not a whole number of frames (left remainder {0}, right remainder {1})', '音频数据大小不是完整帧的整数倍（左侧余数 {0}，右侧余数 {1}）', '音声データのサイズがフレーム単位ではありません（左の余り {0}、右の余り {1}）'),
('length mismatch ({0} vs {1} frames); re-run with --pad to pad the shorter side with silence', '长度不一致（{0} 与 {1} 帧）；请启用静音补齐或使用 --pad 重试', '長さが一致しません（{0} と {1} フレーム）。無音補完を有効にするか --pad を指定して再実行してください'),
("BWF TimeReference differs (L={0}, R={1}); the stereo file keeps the left file's bext chunk", 'BWF TimeReference 不一致（L={0}，R={1}）；立体声文件保留左侧文件的 bext 块', 'BWF TimeReference が異なります（L={0}、R={1}）。ステレオファイルには左側の bext チャンクを保持します'),
]

# WAV parser/writer diagnostics, including errors normally only encountered with
# malformed headers. These are also recognized after an opaque path prefix.
_CATALOG += [
('extensible fmt chunk is shorter than 40 bytes', '扩展 fmt 块不足 40 字节', '拡張 fmt チャンクが 40 バイト未満です'),
('unsupported extensible subformat', '不支持此扩展子格式', 'この拡張サブフォーマットには対応していません'),
('unsupported extensible subformat {0}', '不支持此扩展子格式：{0}', 'この拡張サブフォーマットには対応していません：{0}'),
('sample rate or byte rate does not fit in the WAV fmt chunk', '采样率或字节率超出 WAV fmt 块的范围', 'サンプルレートまたはバイトレートが WAV fmt チャンクの範囲を超えています'),
('extensible fmt requires a 16-byte subformat GUID', '扩展 fmt 需要 16 字节的子格式 GUID', '拡張 fmt には 16 バイトのサブフォーマット GUID が必要です'),
('sample count cannot be negative', '采样数不能为负数', 'サンプル数は負にできません'),
('files over 4 GB must use RF64 or BW64', '超过 4 GB 的文件必须使用 RF64 或 BW64', '4 GB を超えるファイルには RF64 または BW64 が必要です'),
('data size cannot be negative', '数据大小不能为负数', 'データサイズは負にできません'),
('file exceeds 4 GB and does not fit in a classic RIFF WAV', '文件超过 4 GB，无法使用传统 RIFF WAV 容器', 'ファイルが 4 GB を超えているため、従来の RIFF WAV には格納できません'),
('interleave inputs must be the same length', '交错输入必须具有相同长度', 'インターリーブする入力の長さは同じである必要があります'),
('audio length is not a whole number of samples', '音频长度不是完整采样的整数倍', '音声の長さがサンプル単位ではありません'),
('file is too small to be a WAV', '文件太小，不是有效的 WAV 文件', 'ファイルが小さすぎるため、有効な WAV ではありません'),
('big-endian RIFX WAVE is not supported', '不支持大端序 RIFX WAVE', 'ビッグエンディアンの RIFX WAVE には対応していません'),
('WAVE file has no data chunk', 'WAVE 文件没有 data 块', 'WAVE ファイルに data チャンクがありません'),
('WAVE file has no fmt chunk', 'WAVE 文件没有 fmt 块', 'WAVE ファイルに fmt チャンクがありません'),
('audio length cannot be negative', '音频长度不能为负数', '音声の長さは負にできません'),
('audio data is truncated', '音频数据被截断', '音声データが途中で切れています'),
('invalid source channel selection', '源声道选择无效', '元ファイルのチャンネル選択が無効です'),
('audio length is not a whole number of frames', '音频长度不是完整帧的整数倍', '音声の長さがフレーム単位ではありません'),
('chunk_frames must be positive', 'chunk_frames 必须大于零', 'chunk_frames は正の値である必要があります'),
('stereo scan requires complete two-channel frames', '立体声扫描需要完整的双声道帧', 'ステレオの走査には完全な 2 チャンネルのフレームが必要です'),
('both stereo channels contain non-silent samples; refusing to discard or mix audio', '两个立体声声道均包含非静音采样；为避免丢弃或混合音频，已拒绝处理', 'ステレオの両チャンネルに無音でないサンプルがあります。音声の破棄や混合を避けるため、処理を中止しました'),
('a fact chunk needs a frame count', 'fact 块需要帧数', 'fact チャンクにはフレーム数が必要です'),
('frame count cannot be negative', '帧数不能为负数', 'フレーム数は負にできません'),
('audio data ended early', '音频数据提前结束', '音声データが予定より早く終わっています'),
('ds64 chunk is too small', 'ds64 块太小', 'ds64 チャンクが小さすぎます'),
('ds64 table is truncated', 'ds64 表被截断', 'ds64 テーブルが途中で切れています'),
('published file is not the file this run wrote', '已发布的文件不是本次写入的文件', '公開されたファイルが今回書き込んだファイルと異なります'),
('audio bytes do not match the source files', '音频字节与源文件不一致', '音声バイト列が元ファイルと一致しません'),
('chunk id must be 4 bytes, got {0}', '块标识必须为 4 字节，实际为 {0}', 'チャンク ID は 4 バイト必要です。実際の値：{0}'),
('unsupported encoding {0}', '不支持此编码：{0}', 'このエンコーディングには対応していません：{0}'),
('fmt chunk is too small ({0} bytes)', 'fmt 块太小（{0} 字节）', 'fmt チャンクが小さすぎます（{0} バイト）'),
('fmt chunk has channels={0}, rate={1}, block_align={2}', 'fmt 块参数无效：channels={0}, rate={1}, block_align={2}', 'fmt チャンクの値が無効です：channels={0}, rate={1}, block_align={2}'),
('only whole-byte sample widths are supported (got {0} bits)', '仅支持整字节采样宽度（实际为 {0} 位）', 'サンプル幅はバイト単位のみ対応しています（実際は {0} ビット）'),
('unsupported sample format {0}-bit {1}', '不支持此采样格式：{0} 位 {1}', 'このサンプル形式には対応していません：{0} ビット {1}'),
('channel count {0} does not fit in fmt', '声道数 {0} 超出 fmt 块的范围', 'チャンネル数 {0} が fmt チャンクの範囲を超えています'),
('unknown container {0}', '未知容器：{0}', '不明なコンテナです：{0}'),
('invalid sample width {0}', '采样宽度无效：{0}', 'サンプル幅が無効です：{0}'),
('not a RIFF, RF64, or BW64 WAVE file (got {0} / {1})', '不是 RIFF、RF64 或 BW64 WAVE 文件（实际为 {0} / {1}）', 'RIFF、RF64、BW64 の WAVE ファイルではありません（実際の値：{0} / {1}）'),
('{0} file must start with a ds64 chunk', '{0} 文件必须以 ds64 块开头', '{0} ファイルは ds64 チャンクで始まる必要があります'),
('frame counts differ ({0} vs {1}) and pad is off', '帧数不一致（{0} 与 {1}），且未启用静音补齐', 'フレーム数が異なり（{0} と {1}）、無音補完が無効です'),
('bad chunk id {0}', '块标识无效：{0}', 'チャンク ID が無効です：{0}'),
('chunk {0} is larger than 4 GB', '块 {0} 大于 4 GB', 'チャンク {0} が 4 GB を超えています'),
('chunk {0} has size 0xFFFFFFFF but no ds64 chunk was found', '块 {0} 的大小为 0xFFFFFFFF，但未找到 ds64 块', 'チャンク {0} のサイズが 0xFFFFFFFF ですが、ds64 チャンクがありません'),
('chunk {0} has size 0xFFFFFFFF but ds64 has no size for it', '块 {0} 的大小为 0xFFFFFFFF，但 ds64 未提供其大小', 'チャンク {0} のサイズが 0xFFFFFFFF ですが、ds64 に対応するサイズがありません'),
('chunk {0} is truncated', '块 {0} 被截断', 'チャンク {0} が途中で切れています'),
]
for _side, _zh, _ja in [('left', '左侧', '左側'), ('right', '右侧', '右側')]:
    _CATALOG.extend([
        (f'{_side} file has {{0}} channels; expected mono or single-active-channel stereo', f'{_zh}文件有 {{0}} 个声道；需要单声道或仅一个声道有声音的立体声', f'{_ja}ファイルに {{0}} チャンネルあります。モノラル、または片側のみ音声があるステレオが必要です'),
        (f'padded the {_side} file with {{0}} silent frames', f'已为{_zh}文件补齐 {{0}} 帧静音', f'{_ja}ファイルに {{0}} フレームの無音を補いました'),
        (f'iXML metadata for selected internal channel {{0}} is unavailable; used a generic {_side.title()} track', f'所选内部声道 {{0}} 没有可用的 iXML 元数据；已使用通用{_zh}轨道', f'選択した内部チャンネル {{0}} の iXML メタデータがないため、汎用の{_ja}トラックを使用しました'),
    ])
    for _detail, _dz, _dj in [('both channels are silent', '两个声道均为静音', '両チャンネルとも無音'), ('the other channel is exactly silent', '另一个声道完全静音', 'もう一方のチャンネルは完全な無音')]:
        _CATALOG.append((f'{_side} source {{0}}: selected internal channel {{1}} for output {_side.upper()} ({_detail})', f'{_zh}源文件 {{0}}：已选择内部声道 {{1}} 用于输出 {_side.upper()}（{_dz}）', f'{_ja}の元ファイル {{0}}：内部チャンネル {{1}} を出力 {_side.upper()} に選択しました（{_dj}）'))
for _unit, _zh, _ja in [('channels', '声道', 'チャンネル'), ('frames', '帧', 'フレーム'), ('Hz', 'Hz', 'Hz'), ('bits', '位', 'ビット')]:
    _CATALOG.append((f'{{0}} {_unit}, expected {{1}}', f'实际为 {{0}} {_zh}，应为 {{1}}', f'実際は {{0}} {_ja}、期待値は {{1}} です'))


def _compile(template: str) -> re.Pattern[str]:
    capture = r'(\d+)' if re.match(r'\{0\} (channels|frames|Hz|bits), expected', template) else '(.*?)'
    return re.compile(''.join(capture if re.fullmatch(r'\{\d+\}', part) else re.escape(part)
                              for part in re.split(r'(\{\d+\})', template)), re.DOTALL)

_RULES = [(_compile(en), zh, ja) for en, zh, ja in _CATALOG]


def _language(language: str) -> int:
    return 1 if language.lower().startswith('zh') else 2 if language.lower().startswith('ja') else 0


def _known(text: str, locale: int) -> str | None:
    starts = r'(?:left file has|right file has|sample rate mismatch|bit depth mismatch|valid-bit mismatch|sample format mismatch|block align does not match|[0-9]+ (?:channels|frames|Hz|bits), expected)'
    if re.match(starts, text):
        parts = re.split(r'; (?=' + starts + ')', text)
        if len(parts) > 1:
            translated = [_known(part, locale) for part in parts]
            if all(part is not None for part in translated):
                return '；'.join(translated)
    for pattern, zh, ja in _RULES:
        match = pattern.fullmatch(text)
        if match:
            return (zh if locale == 1 else ja).format(*match.groups())
    # Format mismatches can contain several complete reasons, some of which
    # themselves contain semicolons. Split only if BOTH sides are recognized.
    for match in re.finditer('; ', text):
        left = _known(text[:match.start()], locale)
        if left is not None:
            right = _known(text[match.end():], locale)
            if right is not None:
                return left + '；' + right
    # A path prefix is never translated. Try recognized diagnostic suffixes,
    # from right to left, so embedded colons in paths are retained.
    for match in reversed(list(re.finditer(': ', text))):
        suffix = _known(text[match.end():], locale)
        if suffix is not None:
            return text[:match.end()] + suffix
    return None


def translate_message(raw: str, language: str) -> str:
    """Translate a single core event/reason, retaining unknown technical details.

    This is not a parser for CLI reports; use :func:`format_gui_report` for them.
    """
    locale = _language(language)
    if not locale:
        return raw
    if raw.endswith('\n'):
        return translate_message(raw[:-1], language) + '\n'
    for prefix, zh, ja in [('warning ', '警告：', '警告：'), ('error ', '错误：', 'エラー：'), ('error: ', '错误：', 'エラー：')]:
        if raw.startswith(prefix):
            return (zh if locale == 1 else ja) + translate_message(raw[len(prefix):], language)
    if raw.startswith('output failed verification: '):
        return ('输出验证失败：' if locale == 1 else '出力の検証に失敗しました：') + translate_message(raw[len('output failed verification: '):], language)
    known = _known(raw, locale)
    if known is not None:
        return known
    return ('技术诊断（原文）：' if locale == 1 else '技術診断（原文）：') + raw


def format_gui_report(report: BatchReport, language: str, *, verbose: bool = False, quiet: bool = False) -> str:
    """Render structured results without attempting to parse user filenames."""
    locale = _language(language)
    if not locale:
        return format_report(report, verbose=verbose, quiet=quiet)
    zh = locale == 1
    tr = lambda value: translate_message(value, language)
    lines: list[str] = []
    for item in report.joined:
        if not quiet:
            verb = ('已合并' if zh else '結合完了') if item.wrote else ('预演：将合并' if zh else '試行：結合予定')
            lines.append(f'{verb}  {item.left.name} + {item.right.name} -> {item.output}')
            if verbose:
                lines.append(f'        {item.sample_rate} Hz, {item.encoding}, {item.frames} ' + ('帧' if zh else 'フレーム') + f', {item.container}')
                if item.time_reference is not None:
                    lines.append(f'        TimeReference {item.time_reference} ' + ('采样' if zh else 'サンプル'))
                if item.chunks:
                    lines.append(('        元数据块：' if zh else '        チャンク：') + ', '.join(item.chunks))
        for warning in item.warnings:
            lines.append(f'警告 {item.output.name}: {tr(warning)}')
    if not quiet:
        for items, label in [(report.unpaired, '未配对' if zh else 'ペアなし'), (report.unmatched, '未匹配' if zh else '規則に一致せず')]:
            for item in items:
                lines.append(f'{label} {item.path}: {tr(item.reason)}')
    for item in report.refused:
        left, right = item.left.name if item.left else '?', item.right.name if item.right else '?'
        lines.append(('已拒绝' if zh else '処理不可') + f' {left} + {right}: {tr(item.reason)}')
    for message in report.errors:
        lines.append(('错误   ' if zh else 'エラー   ') + tr(message))
    labels = ('汇总', '合并', '未配对', '未匹配', '拒绝', '错误') if zh else ('集計', '結合', 'ペアなし', '規則不一致', '処理不可', 'エラー')
    counts = [len(report.joined), len(report.unpaired), len(report.unmatched), len(report.refused), len(report.errors)]
    lines.append(labels[0] + ' ' + ' '.join(f'{label}={count}' for label, count in zip(labels[1:], counts)))
    return '\n'.join(lines)
