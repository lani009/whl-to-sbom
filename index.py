import shutil
import subprocess
import tarfile
import urllib.request
import zipfile
from pathlib import Path
import datetime

ZIP_EXTENSIONS = (".whl", ".zip")
TAR_EXTENSIONS = (".tar.gz", ".tar.bz2", ".tar.xz")
SUPPORTED_ARCHIVES = ZIP_EXTENSIONS + TAR_EXTENSIONS

SYFT = "https://github.com/anchore/syft/releases/download/v1.42.3/syft_1.42.3_windows_amd64.zip"
SYFT_ZIP_PATH = Path("./bin/syft.zip")
SYFT_EXTRACTED_DIR = Path("./bin/syft")
Path("./bin").mkdir(parents=True, exist_ok=True)

INPUT_DIR = Path("./packages")
OUTPUT_DIR = Path("./temp")
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

ANSI_COLORS = {
    "GREEN": "\033[92m",
    "RED": "\033[91m",
    "YELLOW": "\033[93m",
    "CYAN": "\033[96m",
    "RESET": "\033[0m",
}

def main():
    files = list(INPUT_DIR.iterdir())

    if not files:
        print_log("입력 폴더가 비어 있습니다", "WARN")
        return

    package_files, other_files = validate_input_dir()

    print_log(f"총 {get_color_message(str(len(files)), 'CYAN')}개의 파일 검색됨")

    if not package_files:
        print_log("지원되는 형식의 파일이 없습니다. 작업을 종료합니다.", "WARN")
        print_log("지원되는 형식: " + ", ".join(SUPPORTED_ARCHIVES), "WARN")
        return

    print(f"{get_color_message('====== 패키지 파일 ======', 'GREEN')}")
    for file in package_files:
        print(f"{get_color_message(file.name, 'GREEN')}")
    print()

    print(f"{get_color_message('====== 지원되지 않는 형식 ======', 'RED')}")
    if not other_files:
        print(f"{get_color_message('없음', 'RED')}")
    for file in other_files:
        print(f"{get_color_message(file.name, 'RED')}")
    print()

    print()
    print(
        f"{get_color_message(f'지원 파일 {len(package_files)} 개', 'GREEN')}, {get_color_message(f'미지원 파일 {len(other_files)} 개', 'RED')}"
    )
    answer = input("계속하시겠습니까? [y/N]: ").strip().lower()
    if answer not in ("y", "yes"):
        print_log("사용자가 작업을 취소했습니다.", "WARN")
        return

    for i, file in enumerate(package_files):
        print_log(f"{i+1}/{len(package_files)}: {file.name} 처리 중")
        try:
            extract_archive(file)
        except Exception as e:
            print_log(f"작업실패: {file.name} - {e}", "ERROR")

    print_log("모든 파일 처리 완료. Syft로 SBOM 생성 시작(이 작업은 시간이 걸릴 수 있습니다)")

    fin_flag = False
    sbom_path = Path(f"sbom_{datetime.datetime.now().strftime('%Y-%m-%d_%H-%M-%S')}.json")
    try:
        download_syft()
        run_syft(sbom_path)
        fin_flag = True
    finally:
        if fin_flag:
            cleanup()
            print_log(f"작업이 완료되었습니다. `{sbom_path}` 파일을 확인하세요.", "INFO")


def validate_input_dir():
    """지원되는 파일 스캔

    Returns
    -------
    package_files : list[Path]
        지원되는 파일 목록(SUPPORTED_ARCHIVES constants 참조)
    not_supported_files : list[Path]
        지원되지 않는 파일 목록
    """
    package_files = []
    not_supported_files = []

    for f in INPUT_DIR.iterdir():
        if f.name == ".gitignore":
            continue
        if f.is_file() and f.name.lower().endswith(SUPPORTED_ARCHIVES):
            package_files.append(f)
        else:
            not_supported_files.append(f)

    return package_files, not_supported_files


def extract_archive(file_path: Path):
    """OUTPUT_DIR에 파일 압축 해제

    Parameters
    ----------
    file_path : Path
        압축 풀 대상

    Raises
    ------
    ValueError
        지원하지 않는 포맷
    """
    target_dir = OUTPUT_DIR / file_path.stem

    if target_dir.exists():
        shutil.rmtree(target_dir)

    target_dir.mkdir(parents=True, exist_ok=True)

    name = file_path.name.lower()

    if name.endswith(ZIP_EXTENSIONS):
        extract_zip(file_path, target_dir)

    elif name.endswith(TAR_EXTENSIONS):
        extract_tar(file_path, target_dir)

    else:
        raise ValueError("지원하지 않는 포맷")


def extract_zip(file_path: Path, target_dir: Path):
    """zip 형식 압축 해제"""
    with zipfile.ZipFile(file_path, "r") as zf:
        safe_extract_zip(zf, target_dir)


def safe_extract_zip(zf: zipfile.ZipFile, target_dir: Path):
    """anti zip slip"""
    base = target_dir.resolve()
    for member in zf.infolist():
        member_path = (target_dir / member.filename).resolve()
        try:
            member_path.relative_to(base)
        except ValueError:
            raise RuntimeError(f"Unsafe path detected: {member.filename}")
    zf.extractall(target_dir)


def extract_tar(file_path: Path, target_dir: Path):
    """tar 형식 압축 해제"""
    with tarfile.open(file_path, "r:*") as tf:
        safe_extract_tar(tf, target_dir)


def safe_extract_tar(tf: tarfile.TarFile, target_dir: Path):
    """anti zip slip"""
    base = target_dir.resolve()
    for member in tf.getmembers():
        member_path = (target_dir / member.name).resolve()
        try:
            member_path.relative_to(base)
        except ValueError:
            raise RuntimeError(f"Unsafe path detected: {member.name}")
    tf.extractall(target_dir)


def download_syft():
    """syft 다운받아서 압축 풀기"""
    urllib.request.urlretrieve(SYFT, SYFT_ZIP_PATH)
    with zipfile.ZipFile(SYFT_ZIP_PATH, "r") as zf:
        zf.extractall(SYFT_EXTRACTED_DIR)


def run_syft(sbom_path: Path):
    """syft로 SBOM 생성"""
    result = subprocess.run(
        [
            str(SYFT_EXTRACTED_DIR / "syft.exe"),
            str(OUTPUT_DIR),
            "-o",
            f"cyclonedx-json={sbom_path}",
        ],
        capture_output=True,
        text=True,
    )
    print(result.stdout)
    if result.returncode != 0:
        raise RuntimeError(f"syft 실행 실패\n{result.stderr}")
    if result.stderr:
        print(result.stderr)


def cleanup():
    """임시 파일 정리"""
    if SYFT_ZIP_PATH.exists():
        SYFT_ZIP_PATH.unlink()
    if SYFT_EXTRACTED_DIR.exists():
        shutil.rmtree(SYFT_EXTRACTED_DIR)
    if OUTPUT_DIR.exists():
        shutil.rmtree(OUTPUT_DIR)


def print_log(message, level="INFO"):
    """로그 출력"""
    if level == "INFO":
        print(f"{get_color_message('[INFO]', 'CYAN')} {message}")
    elif level == "WARN":
        print(f"{get_color_message('[WARN]', 'YELLOW')} {message}")
    elif level == "ERROR":
        print(f"{get_color_message('[ERROR]', 'RED')} {message}")


def get_color_message(message, color="GREEN"):
    """컬러 메시지 리턴"""
    if color == "GREEN":
        return f"{ANSI_COLORS['GREEN']}{message}{ANSI_COLORS['RESET']}"
    elif color == "CYAN":
        return f"{ANSI_COLORS['CYAN']}{message}{ANSI_COLORS['RESET']}"
    elif color == "YELLOW":
        return f"{ANSI_COLORS['YELLOW']}{message}{ANSI_COLORS['RESET']}"
    elif color == "RED":
        return f"{ANSI_COLORS['RED']}{message}{ANSI_COLORS['RESET']}"
    else:
        return message


if __name__ == "__main__":
    main()
