# SCG_StereoRejoin

[English](README.md)

SCG_StereoRejoin 把 **Pro Tools**、**Cubase**、**Nuendo** 导出的双单声道拆分 WAV 拼回一个交错立体声 WAV。常见情况是左、右各一个单声道文件，文件里带有 BWF（`bext`）和 iXML。拼完之后它应该重新成为一条立体声素材。

采样是**按字节原样拷贝**的。工具不重采样、不加抖、不改变位深。结果超过 4 GB 时写成 **RF64**（需要的话也可以写成 **BW64**）。BWF 时间戳会保留，立体声文件可以贴回原来的时间线位置。

```
Dialogue.L.wav  ─┐
                 ├─►  Dialogue.wav     L R L R L R ...
Dialogue.R.wav  ─┘
```

## 为什么用 Python

做成单个 Rust 或 Go 可执行文件，丢到没有编译环境的工作室机器上会更省事。这个项目仍然用 Python，原因有四条：

1. 难的是容器，不是运算。`bext`、iXML、cue、LIST/INFO，以及 RF64/BW64 的长度字段都必须仍然合法。Python 标准库（`struct`、`xml.etree`）可以直接把这些行为测清楚。
2. 交错是按步长拷贝字节，音频按块往外写。几 GB 的一对文件不必全部进内存，也不依赖本地音频库。
3. 运行时没有必须安装的第三方包。窗口用 Tk，macOS 和 Windows 上 python.org 的安装包自带。
4. 测试覆盖配对、位精确采样、元数据，以及采样率 / 位深 / 长度不一致时的处理。这是「没有偷偷转码」的依据。

同一套代码在 macOS（Apple 芯片和 Intel）、Windows、Linux 上运行。它不调用 Core Audio、WASAPI 或其他系统音频接口。

## 安装

需要 Python 3.10 或更新版本。

macOS 与 Linux：

```bash
git clone https://github.com/umikado/SCG_StereoRejoin.git
cd SCG_StereoRejoin
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -e .
```

Windows（PowerShell）：

```powershell
py -3 -m venv .venv
.venv\Scripts\Activate.ps1
py -3 -m pip install -e .
```

Debian / Ubuntu 上开窗口还需要 Tk：`sudo apt install python3-tk`。macOS 和 Windows 用 python.org 的安装包时已经带了。

确认安装：

```bash
scg-stereorejoin --help
```

也可以不安装，在源码目录里执行 `PYTHONPATH=src python -m scg_stereorejoin`。

窗口若要接收从访达、资源管理器拖进来的文件，另外安装：

```bash
python -m pip install tkinterdnd2
```

没装这个包时，用「添加文件 / 添加文件夹」即可。

## 马上试一次

仓库里的 `examples/` 是一小套拆分文件：24 bit、16 bit、32 bit float，几种常见命名，一个子文件夹，以及一个没有搭档的文件。

```bash
scg-stereorejoin -r -o ./stereo ./examples
```

会得到 `stereo/Dialogue.wav`、`stereo/Print.wav`、`stereo/Fx.wav`、`stereo/Crowd.wav`、`stereo/Ambience.wav` 和 `stereo/session/Boom.wav`。`Orphan.L.wav` 会被报告出来，命令本身仍然成功。

`Dialogue.wav` 保留左文件的 BWF 时间参考，**230400000** 个采样。48 kHz 下是 **01:20:00.000**。放进一个 48 kHz 的工程里，对一下贴点。

想重新生成示例：

```bash
python -m scg_stereorejoin.samples ./examples
```

只拼两个文件，结果写在左文件旁边：

```bash
scg-stereorejoin Dialogue.L.wav Dialogue.R.wav
```

## 命令行

```text
scg-stereorejoin [选项] 路径...
```

路径可以是 WAV，也可以是文件夹，可以写多个。

| 选项 | 作用 |
| --- | --- |
| `-o`、`--output 目录` | 写到这个目录。输入是扫描出来的文件夹时，子目录结构会保留。不写的话，立体声文件放在左文件旁边。 |
| `-r`、`--recursive` | 进入子文件夹。 |
| `--pattern 左/右` | 增加一对后缀，可重复。前导空格算数，请加引号：`--pattern ' L/ R'`。 |
| `--patterns-file 文件` | 一行一对 `左/右`。`#` 开头是注释。不要缩进，` L/ R` 里的空格是模式的一部分。 |
| `--no-default-patterns` | 只用你给出的模式。 |
| `--pad` | 长度不同：短的一侧用零字节补齐（整数 PCM 和 float 的静音都是零），并给出警告。 |
| `--overwrite` | 覆盖已经存在的输出文件。不会替换本批次里的任何一个输入 WAV。 |
| `--delete-sources` | 输出校验通过之后，把仍是当初读到的那一版的单声道文件移进 `.scg_stereorejoin_trash/`。垃圾桶里的副本会保留。 |
| `--bw64` | 输出超过 4 GB 时用 BW64，而不是默认的 RF64。 |
| `-n`、`--dry-run` | 只打印计划（包括拒绝原因），不写文件。 |
| `--json` | 打印 JSON 报告。退出码规则不变。 |
| `-v`、`--verbose` | 附加采样率、编码、帧数、TimeReference 和块 ID。 |
| `-q`、`--quiet` | 只保留警告、拒绝、错误和汇总行。 |
| `--gui` | 打开窗口。一并传入的路径和选项会填进窗口。 |
| `--version` | 打印 `SCG_StereoRejoin` 和版本号。 |

退出码 **0**：能检查的每一对都拼好了。缺少搭档、对不上命名，都会报告，但不会让命令失败。退出码 **1**：有一对被拒绝，或某个路径出错。退出码 **2**：命令本身写错了（例如模式格式不对）。

下面这些情况会拒绝这一对，并且不写出立体声文件：

- 采样率、位深、有效位，或整数 / 浮点格式不一致
- 其中一侧不是单声道
- 长度不一致，且没有加 `--pad`
- 输出路径已存在，且没有加 `--overwrite`
- 两对文件会写成同一个路径
- 输出路径是本批次里的任何一个输入 WAV，即使加了 `--overwrite` 也一样
- 数据块不完整，或文件不是 RIFF、RF64、BW64 的 WAVE

整批会先规划再写入。某一对被拒绝后，其余文件继续处理。每个源文件用同一个已打开的句柄解析头部并读取音频，所以中途把路径换成新导出的文件，不会改掉已经在读的头部或采样。每个输出都先写到目标目录里一个独占创建的临时文件，名字不会重复，因此另一次运行不会共用它，已经存在的 `*.partial` 也不会被占用。写入失败时这个临时文件会被删掉。没有 `--overwrite` 时，最终文件名用硬链接发布，名字已经存在就会失败，所以两次运行不会互相覆盖。加了 `--overwrite` 才会原子替换这个名字。同一次输出的发布、校验和移走源文件共用一把排他锁。`--delete-sources` 不会按路径直接删除源文件。它先把文件改名到同一文件系统上的 `.scg_stereorejoin_trash/<运行号>/`，再核对这个已移走文件的 inode 和音频摘要。核对通过就留在垃圾桶里（要彻底删掉就自己删这个目录）。核对失败时，如果原路径空着，就链回去；原路径已经被占了，就留在垃圾桶里，并给出警告。如果别的运行在这次发布之后换掉了输出文件，源文件留在原地。

## 配对

配对**只在同一个文件夹里**进行。`reel1/Kick.L.wav` 和 `reel2/Kick.R.wav` 不会配成一对，避免两场戏里同名素材被拼到一起。

匹配不区分大小写。输出文件名沿用左文件的大小写和扩展名，并去掉声道后缀。`vox.l.WAV` 加 `Vox.r.wav` 得到 `vox.WAV`。

内置后缀：

| 左 | 右 | 例子 | 输出 |
| --- | --- | --- | --- |
| `.L` | `.R` | `Kick.L.wav` | `Kick.wav` |
| `_L` | `_R` | `Oh_L.wav` | `Oh.wav` |
| `-L` | `-R` | `Hat-L.wav` | `Hat.wav` |
| ` L` | ` R` | `Room L.wav` | `Room.wav` |
| `.1` | `.2` | `Amb.1.wav` | `Amb.wav` |
| `_1` | `_2` | `Fol_1.wav` | `Fol.wav` |
| `Left` | `Right` | `Crowd Left.wav`、`Mic_Left.wav` | `Crowd.wav`、`Mic.wav` |

`Left` / `Right` 按完整词匹配。后缀要么就是整个文件名，要么它前面的字符不能是字母或数字。所以 `Bright.wav` 不会被当成右声道，`Bleft.wav` 也不会被当成左声道。`Mic_Left.wav` 和 `Mic-Right.wav` 都会收成 `Mic`，然后配成一对。`Take1.wav` 对不上 `_1`。

多个模式同时能配上时，取最长的后缀。你自己的模式排在内置模式前面，因此 `--pattern .SL/.SR` 会把 `Drum.SL.wav` 和 `Drum.SR.wav` 拼成 `Drum.wav`。内置的 `.L` 含有点号，不会误配 `.SL`。

`Left.wav` 加 `Right.wav` 去掉后缀后词干是空的，输出名为 `stereo.wav`。

只匹配到一侧、找不到另一侧的，记为 **unpaired**。WAV 文件名对不上任何模式的，记为 **unmatched**（同一文件夹里已经拼好的立体声文件会出现在这里）。其他扩展名忽略。扫描文件夹时忽略隐藏文件和 AppleDouble 的 `._` 文件；你在命令行上直接写出的路径仍会读取。

同一个文件夹里有多份文件争同一个词干（例如同时有 `Song.L.wav`、`Song_L.wav` 和 `Song.R.wav`）时，这一组会被拒绝，避免配错对象。

## 音频

支持的采样格式，包括 `WAVE_FORMAT_EXTENSIBLE`：

- 16 bit、24 bit、32 bit 整数 PCM
- 32 bit、64 bit IEEE 浮点

两侧的采样率、容器位宽、有效位，以及整数还是浮点，必须一致。32 bit 整数和 32 bit 浮点是两种格式。可扩展格式的单声道文件可以带不同的声道掩码（前左、前右）；立体声文件使用标准的前左 + 前右掩码（`0x3`）。采样字节仍然是拷贝，不是转换。

`--pad` 用零补齐较短的一侧。原来就有的采样保持位精确。日志会写明补了多少帧静音、补在哪一侧。

## 元数据与贴回时间线

尽量从**左文件**按字节保留：

- `bext`（描述、创建者、创建日期和时间、**TimeReference**、UMID、响度字段、编码历史）
- `cue `
- `LIST` / INFO，以及其他可以安全保留的块

`fmt ` 会按两个声道重写：声道数、块对齐和每秒字节数会变，采样编码不变。浮点文件，或源文件里本来就有 `fact` 时，`fact` 里写的是**帧数**（每声道的采样数），不是帧数乘以 2。

iXML 会就地更新：

- `TRACK_COUNT` 改为 2
- 第 1 轨为 Left，第 2 轨为 Right，`CHANNEL_INDEX` 和 `INTERLEAVE_INDEX` 分别是 1 和 2
- 右轨的名字和其余字段，在右文件的 iXML 能解析时取自右文件
- 右文件没有 iXML 时，克隆左轨，并把明显的左侧后缀（`.L`、`_Left` 等）镜像成右侧
- 只有 `FILE_SET / TOTAL_FILES` 正好是 `2`（就是这一对）时才改成 1。更大的文件集保持原样
- 工程、场景、条次、速度，以及 `TIMESTAMP_SAMPLES_SINCE_MIDNIGHT_*` 保持不变

iXML 如果不是合法 XML，就原样拷贝，并在日志里说明。音频仍然会拼。

左文件没有 `bext`、右文件有时，改用右文件的块，并给出警告。两侧 TimeReference 不一致时，保留左文件的块，日志里同时写出两个数。两侧都没有 `bext` 时，拼接仍然进行，日志会说明 DAW 无法按 BWF 时间戳贴回。

填充块（`JUNK`、`FLLR`、`PAD`）会丢掉。它们只是填充，包括有些写入器为以后的 `ds64` 预留的占位。

Pro Tools、Cubase 和 Nuendo 用 BWF 的 TimeReference 贴回时间线（Nuendo / Cubase 也会读 iXML 里的午夜采样时间戳）。这两个值都来自当初的导出，工具不会再去挪动。如果拆分导出时根本没有写 BWF，文件仍能拼上，但 DAW 会把它放在光标处，而不是原来的时间线位置。

## 超过 4 GB 的文件

经典 RIFF 用 32 位记录文件长度，超过 4 GB 就写不下。立体声结果放不下时，SCG_StereoRejoin 写成 **RF64**：容器标识是 `RF64`，32 位长度写成哨兵值 `0xFFFFFFFF`，真正的文件长度、数据长度和帧数放在 `ds64` 块里。`--bw64` 使用同一结构，容器标识改为 `BW64`（EBU Tech 3306 / ITU-R BS.2088）。

没超过限制的文件仍是普通的 `RIFF` / `WAVE`，旧软件也能打开。音频是按块写出的，进程不需要一块和成品一样大的缓冲区。磁盘上需要能放下这条立体声（大约是两个单声道之和）。

## 窗口

```bash
scg-stereorejoin --gui
scg-stereorejoin-gui
```

添加文件或文件夹，选择输出目录（留空表示写在左文件旁边），改配对模式，然后按 Rejoin。窗口里「包含子文件夹」默认打开；命令行里的 `-r` 默认关闭。删除源文件之前会再问一次。模式文本框替换内置列表；打开时已经填好默认值，包括那一行开头带空格的模式。

安装了 `tkinterdnd2` 之后，可以把文件或文件夹拖到列表上。

## 导出时就不要拆开

只有工程已经按双单声道导出了，才需要用这个工具补回来。

**Pro Tools。** 在 Bounce Mix，以及 Export Clips as Files（Export Selected）里，把格式设为 **Interleaved**。**Multiple Mono** 就是这里要收回来的拆分导出。文件类型选 WAV（BWF），时间戳才会跟着文件走。

**Cubase 与 Nuendo。** 文件 → 导出 → 音频缩混（Audio Mixdown）。文件类型选 Wave。不要勾选 **Split Channels（分离声道）**。如果对话框给的是声道模式下拉菜单而不是复选框，选 **Stereo Interleaved（立体声交错）**，或 Interleaved / Multi Channel Interleaved。Split、Mono Downmix、Separate Channels 导出的就是本工具要拼回去的那些文件。

正确的立体声导出是一个文件。拆分导出是成对的文件，名字差在 `.L`/`.R`、`_L`/`_R` 或 `Left`/`Right`。

## 测试

```bash
python -m pip install -e ".[dev]"
pytest
```

测试自己生成单声道 WAV（不需要 DAW），并检查：

- 16/24/32 bit PCM 和 32/64 bit float 的位精确交错，包括块大小不能整除文件长度的情况
- `bext` 字节、cue、LIST/INFO，以及 iXML 的轨列表和文件集
- 配对，包括 `Bright` / `Bleft`、自定义模式，以及不同文件夹
- 采样率、格式、长度不一致，以及 `--pad`、`--overwrite`、`--delete-sources`
- 强制写成 RF64 和 BW64 的往返，以及超过 4 GB 时选择 64 位容器的规则
- 用示例包跑一遍命令行

## 目录

```text
src/scg_stereorejoin/   库、命令行、窗口、示例生成器
tests/                  pytest
examples/               小型拆分单声道文件
```

容器和时间戳依据：EBU Tech 3285（BWF `bext`）、iXML 规范（轨列表和文件集），以及 EBU Tech 3306 / ITU-R BS.2088（RF64 与 BW64）。
