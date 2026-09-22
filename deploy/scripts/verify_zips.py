import zipfile

for name in ['layer.zip', 'function.zip']:
    with zipfile.ZipFile(name) as zf:
        names = zf.namelist()
        has_backslash = any('\\' in n for n in names)
        has_pyd = any(n.endswith('.pyd') for n in names)
        print(f"{name}: {len(names)} entries, backslashes={has_backslash}, .pyd files={has_pyd}")
