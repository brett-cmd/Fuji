import os
import re
import subprocess
from datetime import datetime
from pathlib import Path
from typing import List

from acquisition.abstract import AcquisitionMethod, Parameters, Report


class SnapshotMountMethod(AcquisitionMethod):
    name = "Snapshot Mount"
    description = "Mount an image containing a snapshot and copy its contents to a destination using ditto with clone flag"

    def execute(self, params: Parameters) -> Report:
        # Initialize report
        report = Report(parameters=params, method=self, start_time=datetime.now())
        
        # Get hardware information for the report
        report.hardware_info = self._gather_hardware_info()
        
        # Get path details
        report.path_details = self._gather_path_info(params.source)
        
        # Create a dialog to select a snapshot image file
        print("Preparing to mount a snapshot image...\n")
        snapshot_image = self._prompt_for_image()
        if not snapshot_image:
            print("No snapshot image was selected. Aborting.")
            return report
        
        # Mount the selected image
        mounted_path = self._mount_snapshot_image(snapshot_image)
        if not mounted_path:
            print("Failed to mount the snapshot image. Aborting.")
            return report
        
        # Create a dialog to select the destination directory
        print("Please select a destination for the copied files...")
        destination_path = self._prompt_for_destination()
        if not destination_path:
            print("No destination was selected. Detaching mounted image and aborting.")
            self._detach_mounted_image(mounted_path)
            return report
        
        # Copy the contents using ditto with clone flag
        success = self._copy_with_ditto(mounted_path, destination_path)
        
        # Detach the mounted image
        detached = self._detach_mounted_image(mounted_path)
        if not detached:
            print("Warning: Failed to detach the mounted image. You may need to detach it manually.")
        
        # Update report
        report.success = success
        report.end_time = datetime.now()
        if success:
            # Add output directory to report
            output_path = Path(destination_path)
            report.output_files.append(output_path)
            # Write report
            self._write_report(report)
        
        return report
    
    def _prompt_for_image(self) -> str:
        """Show a dialog to select the snapshot image file."""
        # Use AppleScript to display a file selection dialog
        script = '''
        tell application "System Events"
            activate
            set theFile to choose file with prompt "Select a snapshot image to mount:" of type {"dmg", "sparseimage", "sparsebundle"}
            return POSIX path of theFile
        end tell
        '''
        try:
            result = subprocess.run(
                ["osascript", "-e", script],
                capture_output=True,
                text=True,
                check=True
            )
            return result.stdout.strip()
        except subprocess.CalledProcessError as e:
            print(f"Error selecting image file: {e}")
            return None
    
    def _prompt_for_destination(self) -> str:
        """Show a dialog to select the destination directory."""
        # Use AppleScript to display a folder selection dialog
        script = '''
        tell application "System Events"
            activate
            set theFolder to choose folder with prompt "Select a destination folder for the copied files:"
            return POSIX path of theFolder
        end tell
        '''
        try:
            result = subprocess.run(
                ["osascript", "-e", script],
                capture_output=True,
                text=True,
                check=True
            )
            return result.stdout.strip()
        except subprocess.CalledProcessError as e:
            print(f"Error selecting destination: {e}")
            return None
    
    def _mount_snapshot_image(self, image_path: str) -> str:
        """Mount the specified image and return the mount point."""
        print(f"Mounting image: {image_path}")
        result, output = self._run_process(["hdiutil", "attach", image_path])
        
        if result != 0:
            print(f"Failed to mount image with error code {result}")
            return None
        
        # Parse the output to find the mount point
        output_lines = output.strip().splitlines()
        volume_lines = [line for line in output_lines if "/Volumes" in line]
        
        if not volume_lines:
            print("No mounted volume found in the output")
            return None
        
        mount_line = volume_lines[0]
        parts = re.split(r'\s+', mount_line, maxsplit=2)
        if len(parts) < 3:
            print(f"Failed to parse mount point from: {mount_line}")
            return None
        
        mount_point = parts[2]
        print(f"Image mounted at: {mount_point}")
        return mount_point
    
    def _detach_mounted_image(self, mount_point: str) -> bool:
        """Detach the mounted image."""
        print(f"Detaching image mounted at: {mount_point}")
        disk_device = self._get_disk_device_from_mount(mount_point)
        if not disk_device:
            print(f"Could not determine disk device for mount point: {mount_point}")
            return False
        
        result = self._run_status(["hdiutil", "detach", disk_device])
        return result == 0
    
    def _get_disk_device_from_mount(self, mount_point: str) -> str:
        """Get the disk device associated with a mount point."""
        try:
            df_output = subprocess.check_output(
                ["df", mount_point], 
                universal_newlines=True
            )
            lines = df_output.strip().splitlines()
            if len(lines) < 2:
                return None
            
            header_line = lines[0]
            data_line = lines[1]
            
            # Parse the df output to get the device
            device = data_line.split()[0]
            return device
        except subprocess.CalledProcessError:
            return None
    
    def _copy_with_ditto(self, source: str, destination: str) -> bool:
        """Copy the contents of the source to the destination using ditto with the clone flag."""
        print(f"Copying files from {source} to {destination} using ditto with clone flag...")
        
        # Create a log file for the ditto operation
        output_directory = Path(destination)
        log_file = output_directory / "ditto_copy.log"
        
        result = self._run_status([
            "ditto", 
            "-c",         # enables clone mode
            "--keepParent",
            source,
            destination
        ], tee=log_file)
        
        if result == 0:
            print(f"Successfully copied files to {destination}")
            print(f"Log file created at {log_file}")
            return True
        else:
            print(f"Failed to copy files with error code {result}")
            return False
