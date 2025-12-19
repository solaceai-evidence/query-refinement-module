"""PyInstaller hook for litellm package to include data files."""
from PyInstaller.utils.hooks import collect_data_files, collect_submodules

# Collect all data files from litellm package
datas = collect_data_files('litellm', include_py_files=False)

# Collect all submodules
hiddenimports = collect_submodules('litellm')

# Additional hidden imports that might be needed
hiddenimports += [
    'litellm.llms',
    'litellm.litellm_core_utils',
    'litellm.litellm_core_utils.tokenizers',
]
