# rezip.py — run with: python rezip.py
import zipfile
import os

def zip_directory(source_dir, output_zip):
    with zipfile.ZipFile(output_zip, 'w', zipfile.ZIP_DEFLATED) as zf:
        for root, dirs, files in os.walk(source_dir):
            for file in files:
                file_path = os.path.join(root, file)
                arcname = os.path.relpath(file_path, source_dir).replace(os.sep, '/')
                zf.write(file_path, arcname)

zip_directory('layer', 'layer.zip')
zip_directory('package', 'function.zip')
