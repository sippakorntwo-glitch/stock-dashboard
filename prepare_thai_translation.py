"""Prepare pinned, checksum-verified Apache/MIT model/runtime before price scans."""
from concurrent.futures import ThreadPoolExecutor
import hashlib
import os
from pathlib import Path
import tarfile
import urllib.request

FILES = (
    ('model.gguf', 'https://huggingface.co/Qwen/Qwen3-4B-GGUF/resolve/bc640142c66e1fdd12af0bd68f40445458f3869b/Qwen3-4B-Q4_K_M.gguf',
     '7485fe6f11af29433bc51cab58009521f205840f5b4ae3a32fa7f92e8534fdf5'),
    ('llama.tar.gz', 'https://github.com/ggml-org/llama.cpp/releases/download/b11349/llama-b11349-bin-ubuntu-x64.tar.gz',
     '7efd2fb72db59f12b05614a709ba6d506b9859e867943955fc9bbd8ee13eccea'),
)


def main():
    root = Path(os.environ.get('THAI_TRANSLATION_DIR', 'work/thai-model'))
    root.mkdir(parents=True, exist_ok=True)
    def get(item):
        name, url, digest = item
        target = root / name
        if not target.exists():
            temporary = root / (name + '.partial')
            with urllib.request.urlopen(url, timeout=60) as response, temporary.open('wb') as out:
                while block := response.read(1024 * 1024):
                    out.write(block)
            temporary.replace(target)
        with target.open('rb') as source:
            actual = hashlib.file_digest(source, 'sha256').hexdigest()
        if actual != digest:
            raise ValueError('Translation dependency checksum mismatch: ' + name)
    with ThreadPoolExecutor(2) as pool:
        list(pool.map(get, FILES))
    with tarfile.open(root / 'llama.tar.gz') as archive:
        archive.extractall(root, filter='data')
    print('Thai translation dependencies verified')


if __name__ == '__main__':
    main()
