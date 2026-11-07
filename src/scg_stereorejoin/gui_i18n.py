"""Static desktop text. Identifiers and filename examples are never translated."""
LANGUAGES = {"en": "English", "zh-CN": "简体中文", "ja": "日本語"}

# English is also the stable catalogue key, keeping the default UI compatible.
TRANSLATIONS = {
    "Language": ("语言", "言語"),
    "Join L/R WAVs: mono, or stereo with one silent channel. Audio stays bit-exact.": ("合并 L/R WAV：支持单声道或一个声道静音的立体声。保留音频原始位数据。", "L/R WAV を結合：モノラル、または片チャンネルが無音のステレオ。音声ビットを保持します。"),
    "Files": ("文件", "ファイル"),
    "Add files": ("添加文件", "ファイルを追加"),
    "Add folder": ("添加文件夹", "フォルダーを追加"),
    "Remove": ("移除", "リストから外す"),
    "Clear": ("清空", "クリア"),
    "Drop files here when tkinterdnd2 is installed. Otherwise use Add files or Add folder.": ("安装 tkinterdnd2 后可拖入文件，也可使用“添加文件”或“添加文件夹”。", "tkinterdnd2 があればドラッグできます。またはファイル／フォルダーを追加してください。"),
    "Drop WAV files or a folder onto the list.": ("将 WAV 文件或文件夹拖入列表。", "WAV ファイルまたはフォルダーをリストにドロップしてください。"),
    "Output folder": ("输出文件夹", "出力フォルダー"),
    "Browse": ("浏览", "参照"),
    "Leave the output folder empty to write each stereo file next to its left source.": ("输出文件夹留空时，每个立体声文件将保存到其左声道源文件旁。", "空欄の場合、各ステレオファイルを左チャンネルの元ファイルと同じ場所に保存します。"),
    "Include subfolders": ("包含子文件夹", "サブフォルダーを含める"),
    "Pad a shorter side with silence": ("为较短的一侧补静音", "短い側の末尾を無音で補う"),
    "Overwrite existing outputs": ("覆盖现有输出文件", "既存の出力を上書き"),
    "Move source files to trash after a successful join": ("合并成功后将源文件移入隐藏回收文件夹", "結合成功後、元ファイルを専用の隠しフォルダーへ移動"),
    "Use BW64 for files over 4 GB": ("超过 4 GB 时使用 BW64", "4 GB を超えるファイルに BW64 を使用"),
    "Dry run": ("仅预演（不写入）", "ドライラン（書き込まない）"),
    "Pairing patterns": ("配对规则", "ペアリング規則"),
    "One LEFT/RIGHT pair per line. A leading space matters: the built-in “ L/ R” line keeps it.": ("每行一组 左/右 后缀。开头的空格有意义：内置“ L/ R”保留此空格。", "1 行に左/右の接尾辞を 1 組。先頭の空白も有効です。既定の「 L/ R」の空白を保持してください。"),
    "Rejoin": ("合并", "結合"),
    "Log": ("日志", "ログ"),
    "WAV source files": ("WAV 源文件", "元の WAV ファイル"),
    "All files": ("所有文件", "すべてのファイル"),
    "Folder of split mono files": ("源 WAV 文件夹", "元の WAV のフォルダー"),
    "Add at least one file or folder.": ("请至少添加一个文件或文件夹。", "ファイルまたはフォルダーを 1 つ以上追加してください。"),
    "Move source files to trash": ("移动源文件至隐藏回收文件夹", "元ファイルを専用の隠しフォルダーへ移動"),
    "Move the original source WAVs into the hidden .scg_stereorejoin_trash folder beside each source after each verified join?": ("每次合并并验证成功后，将原始 WAV 源文件移入各源文件旁的隐藏文件夹 .scg_stereorejoin_trash？这不是 macOS 废纸篓。", "結合の検証に成功するたびに、元の WAV をそれぞれの元ファイルと同じ場所にある隠しフォルダー .scg_stereorejoin_trash に移動しますか？macOS のゴミ箱ではありません。"),
    "Patterns": ("配对规则", "ペアリング規則"),
    "Yes": ("是", "はい"),
    "No": ("否", "いいえ"),
    "OK": ("确定", "OK"),
}

TOOLTIPS = {
    "recursive": (
        "Scan WAV files in added folders and all their subfolders. When off, scan only the added folder itself. Files pair only within the same folder.",
        "扫描所添加文件夹及所有子文件夹中的 WAV。关闭时仅扫描所添加文件夹本身。只在同一文件夹内配对。",
        "追加したフォルダーとすべてのサブフォルダーの WAV を検索します。オフの場合は直下のみ。ペアは同じフォルダー内で作られます。"),
    "pad": (
        "If the two sides have different frame counts, append zero-valued samples to the shorter side. No stretching or resampling. Sample rates and audio formats must still match.",
        "两侧帧数不同时，在较短一侧末尾补零值采样。不会拉伸或重采样；采样率和音频格式仍须一致。",
        "左右のフレーム数が異なる場合、短い側の末尾にゼロ値のサンプルを追加します。時間伸縮やリサンプリングは行いません。サンプルレートと音声形式は一致する必要があります。"),
    "overwrite": (
        "Write a temporary output, atomically replace the existing output, then verify the published file. An output that collides with an input is never allowed. Leave off to keep existing outputs.",
        "先写入临时输出，再以原子替换方式覆盖现有输出，随后验证已生成的输出文件。绝不允许输出路径与输入文件冲突。关闭以保留现有输出。",
        "一時出力を書き込み、既存の出力をアトミックに置き換えてから、出力先のファイルを検証します。入力と同じパスへの出力は許可しません。既存の出力を残す場合はオフにしてください。"),
    "delete": (
        "After a successful, verified join, move each source into the hidden .scg_stereorejoin_trash folder beside that source. This is NOT macOS Trash. Dry run never moves sources.",
        "合并成功且验证通过后，将各源文件移入其旁边的隐藏文件夹 .scg_stereorejoin_trash。这不是 macOS 废纸篓。预演不会移动源文件。",
        "結合と検証に成功した後、各元ファイルを同じ場所の隠しフォルダー .scg_stereorejoin_trash へ移動します。macOS のゴミ箱ではありません。ドライランでは移動しません。"),
    "bw64": (
        "For output larger than the 4 GB RIFF limit, use BW64 instead of the default RF64. Smaller output remains RIFF WAV. This changes the container, not the audio samples.",
        "输出超过 RIFF 的 4 GB 限制时，用 BW64 代替默认的 RF64。较小输出仍为 RIFF WAV。只改变容器，不改变音频采样。",
        "出力が RIFF の 4 GB 制限を超える場合、既定の RF64 の代わりに BW64 を使用します。小さい出力は RIFF WAV のままです。音声サンプルは変更しません。"),
    "dry": (
        "Scan, pair and validate the sources, then report the planned outputs. Do not write output files or move any sources. Turn off to perform the actual join.",
        "扫描、配对并验证源文件，报告计划输出。不写入输出文件，也不移动任何源文件。关闭后才会实际合并。",
        "元ファイルを検索・ペアリング・検証し、出力予定を表示します。出力の書き込みも元ファイルの移動も行いません。実際に結合するにはオフにしてください。"),
    "patterns": (
        "One literal LEFT/RIGHT filename suffix pair per line, before .wav; matching ignores case. Examples: Take.L/Take.R (.L/.R), Take_L/Take_R (_L/_R), Take-L/Take-R (-L/-R), Take L/Take R ( L/ R), Take.1/Take.2 (.1/.2), Take_1/Take_2 (_1/_2). Keep both leading spaces in “ L/ R”. Left/Right matches whole ending tokens: Take_Left/Take_Right match, Bleft/Bright do not. Blank lines and # comments are ignored. This editor replaces the default list.",
        "每行填写一组位于 .wav 前的字面左/右文件名后缀，不区分大小写。例如：Take.L/Take.R（.L/.R）、Take_L/Take_R（_L/_R）、Take-L/Take-R（-L/-R）、Take L/Take R（ L/ R）、Take.1/Take.2（.1/.2）、Take_1/Take_2（_1/_2）。“ L/ R”两侧的开头空格都须保留。Left/Right 只匹配末尾完整词：Take_Left/Take_Right 可匹配，Bleft/Bright 不匹配。忽略空行和 # 注释。本编辑器内容替代默认列表。",
        "1 行に .wav の直前にある左/右の接尾辞を文字どおり入力します。大文字・小文字は区別しません。例：Take.L/Take.R（.L/.R）、Take_L/Take_R（_L/_R）、Take-L/Take-R（-L/-R）、Take L/Take R（ L/ R）、Take.1/Take.2（.1/.2）、Take_1/Take_2（_1/_2）。「 L/ R」の両側の先頭空白を保持してください。Left/Right は末尾の独立した語のみ一致し、Take_Left/Take_Right は一致、Bleft/Bright は不一致です。空行と # コメントは無視されます。この内容が既定の一覧を置き換えます。"),
}

def translate(text: str, language: str = "en") -> str:
    if language == "en" or text not in TRANSLATIONS:
        return text
    return TRANSLATIONS[text][0 if language == "zh-CN" else 1]


def tooltip_text(key: str, language: str = "en") -> str:
    return TOOLTIPS[key][{"en": 0, "zh-CN": 1, "ja": 2}.get(language, 0)]
