import requests
import json
import csv
import wave
import io
import pathlib
import struct
import logging
import argparse
import sys
from typing import List, Tuple, Dict, Optional, Any

# --- Logging Configuration ---
LOG_LEVEL = logging.INFO
LOG_FORMAT = '%(asctime)s - %(levelname)s - [%(filename)s:%(lineno)d] - %(message)s'

logging.basicConfig(level=LOG_LEVEL, format=LOG_FORMAT)

# --- Type Aliases ---
SpeakerId = int
AudioBytes = bytes
SegmentData = Tuple[SpeakerId, AudioBytes]
SegmentList = List[SegmentData]
WaveParams = Tuple[int, int, int] # nchannels, sampwidth, framerate
SpeakerMap = Dict[str, SpeakerId]

# --- Constants ---
DEFAULT_VOICEVOX_URL = 'http://localhost:50021'
DEFAULT_TIMEOUT_QUERY = 10
DEFAULT_TIMEOUT_SYNTHESIS = 60
DEFAULT_SILENCE_SAME_SPEAKER = 0.125
DEFAULT_SILENCE_DIFF_SPEAKER = 0.25

def synthesize_voice_bytes(text: str, speaker_id: SpeakerId, voicevox_url: str, timeout_query: int, timeout_synthesis: int) -> Optional[AudioBytes]:
    """
    指定されたテキストと話者IDで音声を合成し、音声データ (bytes) を返す。
    失敗した場合は None を返す。
    VOICEVOX URLとタイムアウト時間を引数で受け取る。
    """
    # speaker_idが整数であることを確認 (型ヒントがあるので厳密には不要だが、念のため)
    if not isinstance(speaker_id, int):
        logging.error(f"Invalid speaker_id type: {speaker_id} (Type: {type(speaker_id)}). Must be an integer.")
        return None

    logging.debug(f"Attempting audio synthesis for speaker {speaker_id}, text: '{text[:30]}...'")
    try:
        # 1. audio_query: 音声合成用のクエリを作成
        logging.debug(f"Sending audio_query request: speaker={speaker_id}, text='{text[:30]}...' to {voicevox_url}")
        query_payload = {'text': text, 'speaker': speaker_id}
        query_response = requests.post(
            f'{voicevox_url}/audio_query',
            params=query_payload,
            timeout=timeout_query
        )
        query_response.raise_for_status() # HTTPエラーの場合は例外を発生させる
        audio_query = query_response.json()
        logging.debug(f"audio_query request successful")

        # 2. synthesis: クエリに基づいて音声データを生成
        logging.debug(f"Sending synthesis request: speaker={speaker_id} to {voicevox_url}")
        synthesis_payload = {'speaker': speaker_id}
        synthesis_response = requests.post(
            f'{voicevox_url}/synthesis',
            params=synthesis_payload,
            json=audio_query,
            timeout=timeout_synthesis
        )
        synthesis_response.raise_for_status() # HTTPエラーの場合は例外を発生させる

        logging.debug(f"Synthesis successful for speaker {speaker_id}, text: '{text[:30]}...'")
        return synthesis_response.content

    except requests.exceptions.Timeout:
        logging.error(f"API request timed out (Speaker: {speaker_id}, Text: '{text[:30]}...')", exc_info=True)
    except requests.exceptions.RequestException as e:
        logging.error(f"API request failed (Speaker: {speaker_id}, Text: '{text[:30]}...')")
        if e.response is not None:
            logging.error(f"  Status Code: {e.response.status_code}")
            try:
                logging.error(f"  Response: {e.response.json()}")
            except json.JSONDecodeError:
                logging.error(f"  Response: {e.response.text}")
        else:
            logging.error(f"  Details: {e}", exc_info=True)
    except Exception as e:
        logging.error(f"Unexpected error during voice synthesis (Speaker: {speaker_id}, Text: '{text[:30]}...')", exc_info=True)

    return None

def read_csv_data(filepath: pathlib.Path) -> Optional[List[Dict[str, str]]]:
    """
    CSVファイルを読み込み、辞書のリスト (各行に1つ) を返す。
    失敗した場合は None を返す。"speaker" と "text" 列が必要。
    filepath は pathlib.Path オブジェクトを受け取る。
    """
    if not filepath.is_file():
        logging.error(f"CSV file not found: {filepath}")
        return None

    data = []
    logging.info(f"Reading CSV file: '{filepath}'")
    try:
        # BOMの可能性があるため、utf-8-sigを使用
        with filepath.open('r', encoding='utf-8-sig') as f:
            reader = csv.DictReader(f)
            if not reader.fieldnames:
                logging.error(f"CSV file '{filepath}' has no header row.")
                return None

            required_columns = ["speaker", "text"]
            if not all(col in reader.fieldnames for col in required_columns):
                missing = [col for col in required_columns if col not in reader.fieldnames]
                logging.error(f"CSV file '{filepath}' is missing required columns: {', '.join(missing)}")
                logging.error(f"       (Required: {', '.join(required_columns)}, Found: {', '.join(reader.fieldnames)})")
                return None

            for i, row in enumerate(reader):
                row_num_csv = i + 2 # CSV行番号 (1から始まるインデックス + ヘッダー)
                if not row:
                    logging.warning(f"CSV line {row_num_csv} in '{filepath}': Row is empty. Skipping.")
                    continue
                # キーの存在を確認し、textは空文字列を許可
                if row.get("speaker") is None or row.get("text") is None:
                    logging.warning(f"CSV line {row_num_csv} in '{filepath}': Missing 'speaker' or 'text' data. Skipping. Row data: {row}")
                    continue
                data.append(row)

    except FileNotFoundError: # pathlibの場合も発生しうるが、is_file()でほぼ防げる
        logging.error(f"CSV file not found: {filepath}")
        return None
    except Exception as e:
        logging.error(f"Error reading CSV file '{filepath}'.", exc_info=True)
        return None

    if not data:
        logging.warning(f"No valid data found in CSV file '{filepath}'.")
        return None # データがない場合は元のロジックに従いNoneを返す

    logging.info(f"Successfully read {len(data)} rows from CSV file '{filepath}'.")
    return data

def parse_speaker_map(map_string: str) -> Optional[SpeakerMap]:
    """
    "CSV話者名:VOICEVOX_ID CSV話者名:VOICEVOX_ID ..." 形式の文字列を解析し、
    {CSV話者名: VOICEVOX_ID (int)} の辞書を返す。
    形式が不正な場合やIDが整数でない場合は None を返す。
    """
    speaker_map: SpeakerMap = {}
    if not map_string or not map_string.strip():
        logging.error("Speaker map string is empty.")
        return None

    pairs = map_string.strip().split()
    logging.debug(f"Parsing speaker map string: '{map_string}'. Found {len(pairs)} pairs.")

    for i, pair in enumerate(pairs):
        parts = pair.split(':')
        if len(parts) != 2:
            logging.error(f"Invalid speaker map format in pair #{i+1}: '{pair}'. Expected 'CSV_SpeakerName:VoicevoxID'.")
            return None
        csv_speaker_name = parts[0].strip()
        voicevox_id_str = parts[1].strip()

        if not csv_speaker_name:
            logging.error(f"Invalid speaker map format in pair #{i+1}: '{pair}'. CSV Speaker Name cannot be empty.")
            return None

        try:
            voicevox_id = int(voicevox_id_str)
            if voicevox_id < 0:
                 logging.error(f"Invalid speaker map format in pair #{i+1}: '{pair}'. VOICEVOX ID must be a non-negative integer, got '{voicevox_id_str}'.")
                 return None
            if csv_speaker_name in speaker_map:
                logging.warning(f"Duplicate CSV speaker name '{csv_speaker_name}' found in speaker map. Using the last definition (ID: {voicevox_id}).")
            speaker_map[csv_speaker_name] = voicevox_id
            logging.debug(f"  Parsed mapping: '{csv_speaker_name}' -> {voicevox_id}")
        except ValueError:
            logging.error(f"Invalid speaker map format in pair #{i+1}: '{pair}'. VOICEVOX ID '{voicevox_id_str}' is not a valid integer.")
            return None

    if not speaker_map:
        logging.error("Speaker map parsing resulted in an empty map, likely due to format errors.")
        return None

    logging.info(f"Successfully parsed speaker map with {len(speaker_map)} entries.")
    return speaker_map

def generate_silence(duration_sec: float, framerate: int, sampwidth: int, nchannels: int) -> bytes:
    """指定されたパラメータで無音の生フレームデータ (bytes) を生成する。"""
    if duration_sec <= 0:
        logging.debug("Skipping silence generation: duration <= 0")
        return b''

    num_frames = int(duration_sec * framerate)
    if num_frames <= 0:
        logging.debug("Skipping silence generation: calculated num_frames <= 0")
        return b''

    # パラメータの検証
    if not all(isinstance(p, int) and p > 0 for p in [framerate, sampwidth, nchannels]):
        logging.error(f"Invalid parameters for silence generation: framerate={framerate}, sampwidth={sampwidth}, nchannels={nchannels}")
        return b''

    total_samples = num_frames * nchannels
    expected_bytes = num_frames * nchannels * sampwidth
    logging.debug(f"Generating silence: duration={duration_sec}s, frames={num_frames}, samples={total_samples}, expected_bytes={expected_bytes}")

    silence_bytes = b''
    try:
        if sampwidth == 1:
            fmt = f"<{total_samples}B" # unsigned char
            silence_bytes = struct.pack(fmt, *([128] * total_samples)) # 8bit PCMの無音は通常128
        elif sampwidth == 2:
            fmt = f"<{total_samples}h" # signed short
            silence_bytes = struct.pack(fmt, *([0] * total_samples))
        elif sampwidth == 3: # 24ビットPCM
            logging.debug("Generating 24-bit PCM silence.")
            silence_bytes = b'\x00' * (total_samples * 3)
            if len(silence_bytes) != expected_bytes:
                 logging.error(f"Generated 24-bit silence data size mismatch: Expected={expected_bytes}, Got={len(silence_bytes)}")
                 return b''
        elif sampwidth == 4:
            fmt = f"<{total_samples}i" # signed int
            silence_bytes = struct.pack(fmt, *([0] * total_samples))
        else:
            logging.error(f"Unsupported sample width {sampwidth}. Cannot generate silence.")
            return b''

        # 生成されたバイト長の検証
        if len(silence_bytes) != expected_bytes:
             logging.warning(f"Generated silence data byte length differs from expected."
                             f" Sampwidth={sampwidth}, Expected={expected_bytes}, Got={len(silence_bytes)}")

        logging.debug(f"Silence generation successful: {len(silence_bytes)} bytes")
        return silence_bytes

    except struct.error as e:
        logging.error(f"struct.pack failed during silence generation (sampwidth={sampwidth}, total_samples={total_samples}): {e}", exc_info=True)
        return b''
    except MemoryError:
        logging.error(f"Memory error during silence generation (Duration: {duration_sec}s, Samples: {total_samples})", exc_info=True)
        return b''
    except Exception as e:
        logging.error(f"Unexpected error during silence generation: {e}", exc_info=True)
        return b''

# --- Helper functions for combine_wav_segments ---

def _validate_and_collect_segments(segments_with_speaker_id: SegmentList) -> Tuple[Optional[WaveParams], SegmentList]:
    """
    WAVセグメントのパラメータを検証し、互換性のあるものを収集する。
    最初の有効なセグメントのパラメータを参照として使用する。
    """
    ref_params: Optional[WaveParams] = None
    valid_segments: SegmentList = []
    first_valid_segment_found = False

    logging.info("Starting parameter check and collection of valid audio segments...")

    for i, (speaker_id, wav_bytes) in enumerate(segments_with_speaker_id):
        segment_label = f"Segment {i+1} (Mapped Speaker ID {speaker_id})"
        if not wav_bytes:
            logging.warning(f"{segment_label}: Audio data is empty. Skipping.")
            continue
        try:
            with io.BytesIO(wav_bytes) as wav_io:
                with wave.open(wav_io, 'rb') as wf:
                    current_params: WaveParams = (wf.getnchannels(), wf.getsampwidth(), wf.getframerate())
                    logging.debug(f"{segment_label}: Parameters - Channels={current_params[0]}, Sampwidth={current_params[1]}, Framerate={current_params[2]}")

                    if not first_valid_segment_found:
                        # 最初の有効なセグメントから参照パラメータを設定
                        ref_params = current_params
                        valid_segments.append((speaker_id, wav_bytes))
                        first_valid_segment_found = True
                        logging.info(f"Reference parameters set: Channels={ref_params[0]}, Sampwidth={ref_params[1]}, Framerate={ref_params[2]}")
                    elif current_params == ref_params:
                        # パラメータが参照と一致する場合、セグメントを追加
                        valid_segments.append((speaker_id, wav_bytes))
                    else:
                        # パラメータが一致しない場合は警告をログに記録し、スキップ
                        logging.warning(f"{segment_label}: Parameters mismatch reference. Skipping.")
                        if ref_params:
                            logging.warning(f"  Reference: Channels={ref_params[0]}, Sampwidth={ref_params[1]}, Framerate={ref_params[2]}")
                        logging.warning(f"  Current:   Channels={current_params[0]}, Sampwidth={current_params[1]}, Framerate={current_params[2]}")

        except wave.Error as e:
            logging.error(f"{segment_label}: Failed to read/parse WAV data. Skipping. Error: {e}", exc_info=True)
        except EOFError:
            logging.error(f"{segment_label}: WAV data is incomplete or corrupted (EOFError). Skipping.", exc_info=True)
        except Exception as e:
            logging.error(f"{segment_label}: Unexpected error processing WAV data. Skipping. Error: {e}", exc_info=True)

    if not valid_segments:
        logging.error("No valid audio segments found after parameter check.")
        return None, []

    if len(valid_segments) < len(segments_with_speaker_id):
        skipped_count = len(segments_with_speaker_id) - len(valid_segments)
        logging.warning(f"{skipped_count} audio segments were skipped due to parameter mismatch, empty data, or errors.")

    return ref_params, valid_segments


def _write_silence(out_wf: wave.Wave_write, duration: float, params: WaveParams) -> int:
    """指定された無音を出力WAVファイルに書き込み、書き込んだフレーム数を返す。"""
    if duration <= 0 or not params:
        return 0

    nchannels, sampwidth, framerate = params
    logging.debug(f"Attempting to insert silence: duration={duration:.3f}s")
    silence_frames_data = generate_silence(duration, framerate, sampwidth, nchannels)

    if silence_frames_data:
        try:
            out_wf.writeframesraw(silence_frames_data)
            bytes_per_silence_frame = nchannels * sampwidth
            if bytes_per_silence_frame > 0:
                num_silence_frames = len(silence_frames_data) // bytes_per_silence_frame
                logging.info(f"Inserted {duration:.3f}s silence ({num_silence_frames} frames).")
                return num_silence_frames
            else:
                logging.warning("Bytes per silence frame is zero. Cannot calculate frame count for silence.")
                return 0
        except Exception as e:
            logging.error(f"Error writing silence frames to output file: {e}", exc_info=True)
            return 0
    else:
        logging.warning(f"Failed to generate {duration:.3f}s silence. Continuing without silence.")
        return 0


def _write_segment(out_wf: wave.Wave_write, wav_bytes: AudioBytes, segment_label: str) -> int:
    """単一の音声セグメントを出力WAVファイルに書き込み、書き込んだフレーム数を返す。"""
    try:
        with io.BytesIO(wav_bytes) as wav_io:
            with wave.open(wav_io, 'rb') as wf:
                frames_data = wf.readframes(wf.getnframes())
                if frames_data:
                    logging.debug(f"Writing {len(frames_data)} bytes of audio data for {segment_label}")
                    out_wf.writeframesraw(frames_data)
                    bytes_per_frame = wf.getnchannels() * wf.getsampwidth()
                    if bytes_per_frame > 0:
                        num_frames = len(frames_data) // bytes_per_frame
                        return num_frames
                    else:
                        logging.warning(f"{segment_label}: Bytes per frame is zero. Cannot calculate frame count.")
                        return 0
                else:
                    logging.warning(f"{segment_label}: Read empty frame data. Skipping write for this segment.")
                    return 0
    except wave.Error as e:
        logging.error(f"{segment_label}: Error reading WAV data during write phase. Skipping segment write. Error: {e}", exc_info=True)
        return 0
    except Exception as e:
        logging.error(f"{segment_label}: Unexpected error during write phase. Skipping segment write. Error: {e}", exc_info=True)
        return 0


# --- Main Combination Function ---

def combine_wav_segments(segments_with_speaker_id: SegmentList, output_filepath: pathlib.Path,
                         silence_duration_same_speaker: float, silence_duration_diff_speaker: float):
    """
    検証済みの (speaker_id, audio_bytes) タプルのリストを結合し、話者の変更に基づいて無音を挿入し、
    出力WAVファイルに書き込む。
    """
    if not segments_with_speaker_id:
        logging.warning("No audio segments provided to combine. Output file will not be created.")
        return

    # 1. パラメータ検証と有効なセグメントの収集
    ref_params, valid_segments = _validate_and_collect_segments(segments_with_speaker_id)

    if not valid_segments or not ref_params:
        logging.error("No valid audio segments to combine after validation. Output file will not be created.")
        return

    logging.info(f"Combining {len(valid_segments)} valid audio segments with silence insertion...")
    nchannels, sampwidth, framerate = ref_params

    # 2. 出力ファイルを開き、結合処理を開始
    try:
        with wave.open(str(output_filepath), 'wb') as out_wf:
            out_wf.setnchannels(nchannels)
            out_wf.setsampwidth(sampwidth)
            out_wf.setframerate(framerate)
            logging.info(f"Opened output file '{output_filepath}' with parameters: Channels={nchannels}, Sampwidth={sampwidth}, Framerate={framerate}")

            total_frames_written = 0
            last_speaker_id: Optional[SpeakerId] = None

            for i, (current_speaker_id, wav_bytes) in enumerate(valid_segments):
                segment_label = f"Valid Segment {i+1}/{len(valid_segments)} (Mapped Speaker ID {current_speaker_id})"

                # 3. 無音の挿入 (2番目以降のセグメント)
                if i > 0 and last_speaker_id is not None:
                    is_speaker_change = (current_speaker_id != last_speaker_id)
                    duration = silence_duration_diff_speaker if is_speaker_change else silence_duration_same_speaker
                    logging.debug(f"Silence check before {segment_label}: Speaker change={is_speaker_change}, Duration={duration:.3f}s")
                    if duration > 0:
                        frames_from_silence = _write_silence(out_wf, duration, ref_params)
                        total_frames_written += frames_from_silence
                    else:
                         logging.debug("Skipping silence insertion (duration is zero or negative).")


                # 4. 音声セグメントの書き込み
                frames_from_segment = _write_segment(out_wf, wav_bytes, segment_label)
                total_frames_written += frames_from_segment

                last_speaker_id = current_speaker_id # 現在の話者IDを記録

            # 5. 成功ログの記録
            logging.info(f"Successfully combined audio and saved to '{output_filepath}'")
            if framerate > 0:
                final_duration_sec = total_frames_written / framerate
                logging.info(f"  Combined {len(valid_segments)} valid segments. Total frames: {total_frames_written}. Estimated duration: {final_duration_sec:.2f} seconds.")
            else:
                logging.warning(f"  Combined {len(valid_segments)} valid segments. Total frames: {total_frames_written}. Cannot calculate duration (framerate is zero).")

    except wave.Error as e:
        logging.error(f"Failed to write combined audio file '{output_filepath}': {e}", exc_info=True)
    except Exception as e:
        logging.error(f"Unexpected error writing combined audio file '{output_filepath}': {e}", exc_info=True)


# --- Main Execution Block ---

if __name__ == "__main__":
    # --- コマンドライン引数の設定 ---
    parser = argparse.ArgumentParser(
        description="VOICEVOXを使ってCSVファイルからセリフを読み上げ、結合したWAVファイルを出力します。",
        formatter_class=argparse.RawTextHelpFormatter # helpメッセージの改行を保持
    )

    # 必須引数
    parser.add_argument(
        "csv_filepath_input",
        type=pathlib.Path,
        help="入力するCSVファイルのパス。"
    )
    parser.add_argument(
        "speaker_map_arg", # 引数名を変更 (--speaker-map と区別)
        metavar="SPEAKER_MAP",
        type=str,
        help=(
            "CSV内の話者名とVOICEVOX話者IDのマッピングを指定します。\n"
            "形式: \"CSV話者名1:ID1 CSV話者名2:ID2 ...\"\n"
            "例: \"SPEAKER_00:8 SPEAKER_01:14\"\n"
            "CSVファイルに登場する全ての話者名を指定する必要があります。"
        )
    )


    # オプション引数
    parser.add_argument(
        "--voicevox_url",
        type=str,
        default=DEFAULT_VOICEVOX_URL,
        help=f"VOICEVOX Engine API エンドポイントURL。(デフォルト: {DEFAULT_VOICEVOX_URL})"
    )
    parser.add_argument(
        "--output_wav_path",
        type=pathlib.Path,
        default=None,
        help="出力するWAVファイルの名前。(デフォルト: input_csv_path.with_suffix('.wav') )"
    )
    parser.add_argument(
        "--timeout_query",
        type=int,
        default=DEFAULT_TIMEOUT_QUERY,
        help=f"audio_queryリクエストのタイムアウト時間 (秒)。(デフォルト: {DEFAULT_TIMEOUT_QUERY})"
    )
    parser.add_argument(
        "--timeout_synthesis",
        type=int,
        default=DEFAULT_TIMEOUT_SYNTHESIS,
        help=f"synthesisリクエストのタイムアウト時間 (秒)。(デフォルト: {DEFAULT_TIMEOUT_SYNTHESIS})"
    )
    parser.add_argument(
        "--silence_duration_same_speaker",
        type=float,
        default=DEFAULT_SILENCE_SAME_SPEAKER,
        help=f"話者が変わらない場合の無音時間 (秒)。(デフォルト: {DEFAULT_SILENCE_SAME_SPEAKER})"
    )
    parser.add_argument(
        "--silence_duration_diff_speaker",
        type=float,
        default=DEFAULT_SILENCE_DIFF_SPEAKER,
        help=f"話者が変わる場合の無音時間 (秒)。(デフォルト: {DEFAULT_SILENCE_DIFF_SPEAKER})"
    )

    # 引数を解析
    args = parser.parse_args()

    # --- パス設定 ---
    input_csv_path: pathlib.Path = args.csv_filepath_input
    output_wav_path: pathlib.Path = input_csv_path.with_suffix(".wav") if args.output_wav_path is None else args.output_wav_path

    # --- Speaker Map の解析 ---
    speaker_map: Optional[SpeakerMap] = parse_speaker_map(args.speaker_map_arg)
    if speaker_map is None:
        logging.error("Failed to parse speaker map. Please check the format of the SPEAKER_MAP argument.")
        sys.exit(1) # エラー終了

    # --- 引数の値をログに出力 ---
    logging.info("Script arguments:")
    logging.info(f"  CSV File Path: {input_csv_path}")
    logging.info(f"  Speaker Map Arg: {args.speaker_map_arg}")
    logging.info(f"    Parsed Map: {speaker_map}")
    logging.info(f"  VOICEVOX URL: {args.voicevox_url}")
    logging.info(f"  Output WAV Path: {output_wav_path}")
    logging.info(f"  Timeout Query: {args.timeout_query}s")
    logging.info(f"  Timeout Synthesis: {args.timeout_synthesis}s")
    logging.info(f"  Silence Same Speaker: {args.silence_duration_same_speaker}s")
    logging.info(f"  Silence Different Speaker: {args.silence_duration_diff_speaker}s")

    logging.info(f"Script execution started.")

    # --- CSV読み込み ---
    dialogue_data: Optional[List[Dict[str, str]]] = read_csv_data(input_csv_path)

    if dialogue_data:
        audio_segments_with_speaker_id: SegmentList = []
        logging.info(f"Starting audio synthesis for {len(dialogue_data)} rows...")

        success_count = 0
        fail_count = 0
        skip_count = 0

        # --- 音声合成ループ ---
        for i, row in enumerate(dialogue_data):
            row_num_script = i + 1 # スクリプトループ用の1から始まるインデックス
            row_num_csv = i + 2   # CSV行番号用の1から始まるインデックス (ヘッダーを含む)
            logging.info(f"Processing row {row_num_script}/{len(dialogue_data)} (CSV line {row_num_csv})...")

            csv_speaker_name: Optional[str] = row.get('speaker')
            text: Optional[str] = row.get('text')

            # 行データチェック
            if not csv_speaker_name:
                 logging.warning(f"  [CSV Line {row_num_csv}] 'speaker' field is empty or missing. Skipping row.")
                 skip_count += 1
                 continue
            if text is None:
                 logging.warning(f"  [CSV Line {row_num_csv}] 'text' field is missing (None). Skipping row.")
                 skip_count += 1
                 continue

            logging.info(f"  Data: csv_speaker='{csv_speaker_name}', text='{text[:40]}...'")

            # Speaker Map から ID を取得
            voicevox_id: Optional[SpeakerId] = speaker_map.get(csv_speaker_name)
            if voicevox_id is None:
                 logging.warning(f"  [CSV Line {row_num_csv}] Speaker name '{csv_speaker_name}' not found in the provided speaker map. Skipping row.")
                 skip_count += 1
                 continue

            logging.info(f"  Mapped VOICEVOX Speaker ID: {voicevox_id}")

            if not text: # 空文字列の場合の警告
                 logging.warning(f"  [CSV Line {row_num_csv}] 'text' field is an empty string. Attempting synthesis, may result in empty audio.")

            # 音声合成実行
            audio_bytes: Optional[AudioBytes] = synthesize_voice_bytes(
                text,
                voicevox_id,
                args.voicevox_url,
                args.timeout_query,
                args.timeout_synthesis
            )

            # 結果の処理
            if audio_bytes:
                audio_segments_with_speaker_id.append((voicevox_id, audio_bytes))
                success_count += 1
                logging.info(f"  [CSV Line {row_num_csv}] Audio synthesis successful. Added to combination list.")
            else:
                logging.error(f"  [CSV Line {row_num_csv}] Audio synthesis failed for speaker ID {voicevox_id}. Segment will not be included in output.")
                fail_count += 1

        # --- 合成サマリー ---
        total_processed = success_count + fail_count + skip_count
        logging.info(f"Audio synthesis processing finished.")
        logging.info(f"Summary: {success_count} succeeded, {fail_count} failed, {skip_count} skipped (Total rows processed: {total_processed})")

        # --- 音声結合 ---
        if audio_segments_with_speaker_id:
            combine_wav_segments(
                audio_segments_with_speaker_id,
                output_wav_path,
                args.silence_duration_same_speaker,
                args.silence_duration_diff_speaker
            )
        else:
            logging.warning("No valid audio segments were generated. Skipping combination process.")

    else:
        logging.error(f"Failed to read data or no data found in '{input_csv_path}'. Cannot proceed.")

    logging.info("Script execution finished.")
