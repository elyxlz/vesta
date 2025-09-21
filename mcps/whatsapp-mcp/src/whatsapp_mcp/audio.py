import os
import subprocess
import tempfile


def convert_to_opus_ogg(input_file, output_file=None, bitrate="32k", sample_rate=24000):
    """Convert audio to Opus format in Ogg container for WhatsApp voice messages."""
    if not os.path.isfile(input_file):
        raise FileNotFoundError(f"Input file not found: {input_file}")

    if output_file is None:
        output_file = os.path.splitext(input_file)[0] + ".ogg"

    output_dir = os.path.dirname(output_file)
    if output_dir and not os.path.exists(output_dir):
        os.makedirs(output_dir)

    cmd = [
        "ffmpeg",
        "-i",
        input_file,
        "-c:a",
        "libopus",
        "-b:a",
        bitrate,
        "-ar",
        str(sample_rate),
        "-application",
        "voip",
        "-vbr",
        "on",
        "-compression_level",
        "10",
        "-frame_duration",
        "60",
        "-y",
        output_file,
    ]

    try:
        subprocess.run(
            cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, check=True
        )
        return output_file
    except subprocess.CalledProcessError as e:
        raise RuntimeError(
            f"Failed to convert audio. You likely need to install ffmpeg {e.stderr}"
        )


def convert_to_opus_ogg_temp(input_file, bitrate="32k", sample_rate=24000):
    """Convert audio to Opus format and store in temporary file."""
    temp_file = tempfile.NamedTemporaryFile(suffix=".ogg", delete=False)
    temp_file.close()

    try:
        convert_to_opus_ogg(input_file, temp_file.name, bitrate, sample_rate)
        return temp_file.name
    except Exception as e:
        if os.path.exists(temp_file.name):
            os.unlink(temp_file.name)
        raise e


if __name__ == "__main__":
    # Example usage
    import sys

    if len(sys.argv) < 2:
        print("Usage: python audio.py input_file [output_file]")
        sys.exit(1)

    input_file = sys.argv[1]

    try:
        result = convert_to_opus_ogg_temp(input_file)
        print(f"Successfully converted to: {result}")
    except Exception as e:
        print(f"Error: {e}")
        sys.exit(1)
