"""
Media Converter API Module
Optimized for API usage - handles individual file conversions
Supports: MP4 to MP3, video compression, and audio format conversions
"""

import os
import io
import tempfile
from typing import Tuple, Optional
from moviepy.editor import VideoFileClip, AudioFileClip
import logging

logger = logging.getLogger(__name__)


class MediaConverterAPI:
    """Media converter optimized for API usage with in-memory processing."""

    @staticmethod
    def convert_to_mp3(
        file_data: bytes, filename: str, bitrate: str = "192k"
    ) -> Tuple[bytes, str]:
        """
        Convert audio/video file to MP3 format.

        Args:
            file_data (bytes): Binary data of the input file
            filename (str): Original filename (used to determine file type)
            bitrate (str): Audio bitrate (e.g., "128k", "192k", "256k", "320k")

        Returns:
            Tuple[bytes, str]: (MP3 file data, output filename)

        Raises:
            Exception: If conversion fails
        """
        temp_input = None
        temp_output = None

        try:
            # Get file extension
            file_ext = os.path.splitext(filename)[1].lower()
            base_name = os.path.splitext(filename)[0]
            output_filename = f"{base_name}.mp3"

            # Create temporary files
            with tempfile.NamedTemporaryFile(suffix=file_ext, delete=False) as tmp_in:
                temp_input = tmp_in.name
                tmp_in.write(file_data)

            with tempfile.NamedTemporaryFile(suffix=".mp3", delete=False) as tmp_out:
                temp_output = tmp_out.name

            logger.info(f"Converting {filename} to MP3 at {bitrate} bitrate...")

            # Handle video files
            if file_ext in [".mp4", ".avi", ".mov", ".mkv", ".flv", ".wmv"]:
                video = VideoFileClip(temp_input)
                video.audio.write_audiofile(
                    temp_output,
                    codec="mp3",
                    bitrate=bitrate,
                    logger=None,  # Suppress moviepy logs
                )
                video.close()

            # Handle audio files
            else:
                audio = AudioFileClip(temp_input)
                audio.write_audiofile(
                    temp_output,
                    codec="mp3",
                    bitrate=bitrate,
                    logger=None,  # Suppress moviepy logs
                )
                audio.close()

            # Read the output file
            with open(temp_output, "rb") as f:
                output_data = f.read()

            logger.info(f"Conversion complete: {filename} -> {output_filename}")
            return output_data, output_filename

        except Exception as e:
            logger.error(f"Error converting {filename} to MP3: {str(e)}")
            raise Exception(f"Failed to convert to MP3: {str(e)}")

        finally:
            # Clean up temporary files
            if temp_input and os.path.exists(temp_input):
                try:
                    os.unlink(temp_input)
                except:
                    pass
            if temp_output and os.path.exists(temp_output):
                try:
                    os.unlink(temp_output)
                except:
                    pass

    @staticmethod
    def compress_video(
        file_data: bytes,
        filename: str,
        resolution: str = "720p",
        bitrate: str = "1000k",
    ) -> Tuple[bytes, str]:
        """
        Compress MP4 video by reducing resolution and/or bitrate.

        Args:
            file_data (bytes): Binary data of the input MP4 file
            filename (str): Original filename
            resolution (str): Target resolution ("1080p", "720p", "480p", "360p")
            bitrate (str): Video bitrate (e.g., "1000k", "2000k", "3000k")

        Returns:
            Tuple[bytes, str]: (Compressed MP4 file data, output filename)

        Raises:
            Exception: If compression fails
        """
        temp_input = None
        temp_output = None

        try:
            # Resolution mapping
            resolution_map = {
                "1080p": (1920, 1080),
                "720p": (1280, 720),
                "480p": (854, 480),
                "360p": (640, 360),
            }

            if resolution not in resolution_map:
                logger.warning(
                    f"Invalid resolution {resolution}. Using 720p as default."
                )
                resolution = "720p"

            target_width, target_height = resolution_map[resolution]

            base_name = os.path.splitext(filename)[0]
            output_filename = f"{base_name}_{resolution}.mp4"

            # Create temporary files
            with tempfile.NamedTemporaryFile(suffix=".mp4", delete=False) as tmp_in:
                temp_input = tmp_in.name
                tmp_in.write(file_data)

            with tempfile.NamedTemporaryFile(suffix=".mp4", delete=False) as tmp_out:
                temp_output = tmp_out.name

            logger.info(f"Compressing {filename} to {resolution}...")

            # Load video
            video = VideoFileClip(temp_input)

            # Get original dimensions
            original_width, original_height = video.size
            logger.info(f"Original resolution: {original_width}x{original_height}")

            # Calculate aspect ratio and resize
            aspect_ratio = original_width / original_height
            new_width = target_width
            new_height = int(new_width / aspect_ratio)

            # Ensure height doesn't exceed target
            if new_height > target_height:
                new_height = target_height
                new_width = int(new_height * aspect_ratio)

            logger.info(f"New resolution: {new_width}x{new_height}, bitrate: {bitrate}")

            # Resize and compress
            resized_video = video.resize((new_width, new_height))
            resized_video.write_videofile(
                temp_output,
                codec="libx264",
                bitrate=bitrate,
                audio_bitrate="128k",
                logger=None,  # Suppress moviepy logs
            )

            video.close()
            resized_video.close()

            # Read the output file
            with open(temp_output, "rb") as f:
                output_data = f.read()

            logger.info(f"Compression complete: {filename} -> {output_filename}")
            return output_data, output_filename

        except Exception as e:
            logger.error(f"Error compressing {filename}: {str(e)}")
            raise Exception(f"Failed to compress video: {str(e)}")

        finally:
            # Clean up temporary files
            if temp_input and os.path.exists(temp_input):
                try:
                    os.unlink(temp_input)
                except:
                    pass
            if temp_output and os.path.exists(temp_output):
                try:
                    os.unlink(temp_output)
                except:
                    pass

    @staticmethod
    def get_video_info(file_data: bytes, filename: str) -> dict:
        """
        Get information about a video file.

        Args:
            file_data (bytes): Binary data of the video file
            filename (str): Original filename

        Returns:
            dict: Video information including duration, resolution, fps, etc.
        """
        temp_input = None

        try:
            file_ext = os.path.splitext(filename)[1].lower()

            with tempfile.NamedTemporaryFile(suffix=file_ext, delete=False) as tmp_in:
                temp_input = tmp_in.name
                tmp_in.write(file_data)

            video = VideoFileClip(temp_input)

            info = {
                "duration": video.duration,
                "resolution": f"{video.w}x{video.h}",
                "width": video.w,
                "height": video.h,
                "fps": video.fps,
                "has_audio": video.audio is not None,
            }

            video.close()

            return info

        except Exception as e:
            logger.error(f"Error getting video info for {filename}: {str(e)}")
            raise Exception(f"Failed to get video info: {str(e)}")

        finally:
            if temp_input and os.path.exists(temp_input):
                try:
                    os.unlink(temp_input)
                except:
                    pass
