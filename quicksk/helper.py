"""
quicksk.helper
"""

import os.path
import re
import subprocess
import time
import winreg
import zipfile

import comtypes.client
from comtypes import COMError
import requests
from packaging import version

def ps_exec(cmd, admin=False):
    """
    用 Power Shell 執行一個指令
    * 可以使用系統管理者執行
    * 參數含有空白時會發生問題, 例如 tasklist 的 /fi
    """
    if isinstance(cmd, list):
        tokens = cmd
    else:
        tokens = cmd.split(' ')
    prog = tokens[0]
    spcmd = [
        'powershell.exe', 'Start-Process',
        '-FilePath', prog
    ]
    if len(tokens) > 1:
        quoted_tokens = list(map(lambda i: '"%s"' % i, tokens[1:]))
        args = ','.join(quoted_tokens)
        spcmd.append('-ArgumentList')
        spcmd.append(args)

    # 用系統管理員身分執行
    if admin:
        # TODO: 需要想一下系統管理員模式怎麼取得 stdout
        spcmd.append('-Verb')
        spcmd.append('RunAs')
    else:
        # 接收 stdout
        spcmd.append('-NoNewWindow')
        spcmd.append('-Wait')

    # Python 3.7 才能用這個寫法
    # completed = subprocess.run(spcmd, capture_output=True)
    completed = subprocess.run(spcmd, stdout=subprocess.PIPE)
    if completed.returncode == 0:
        return completed.stdout.decode('cp950')

    return None

def cmd_exec(cmd):
    """
    用 cmd 執行一個指令
    * 適用指令較廣泛
    * 無法使用系統管理者身分執行
    """
    if isinstance(cmd, list):
        tokens = cmd
    else:
        tokens = cmd.split(' ')

    spcmd = ['cmd', '/C'] + tokens
    # Python 3.7 才能用這個寫法
    # completed = subprocess.run(spcmd, capture_output=True)
    completed = subprocess.run(spcmd, stdout=subprocess.PIPE)
    if completed.returncode == 0:
        # 因為被 cmd 包了一層, 不管怎樣都是 return 0
        return completed.stdout.decode('cp950')

    return None

def verof_vcredist():
    """
    取得 Visual C++ 2010 可轉發套件版本資訊
    """
    try:
        # 版本字串格式: v10.0.40219.325
        keyname = r'SOFTWARE\WOW6432Node\Microsoft\VisualStudio\10.0\VC\VCRedist\x64'
        key = winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, keyname)
        pkg_ver = winreg.QueryValueEx(key, 'Version')[0].strip('v')
        if not re.match(r'(\d+\.){3}\d+', pkg_ver):
            pkg_ver = '0.0.0.0'
    except FileNotFoundError:
        pkg_ver = '0.0.0.0'

    return version.parse(pkg_ver)

def install_vcredist():
    """
    安裝 Visual C++ 2010 x64 Redistributable 10.0.40219.325
    """

    # 下載與安裝
    url = 'https://download.microsoft.com/download/1/6/5/' + \
          '165255E7-1014-4D0A-B094-B6A430A6BFFC/vcredist_x64.exe'
    vcdist = download_file(url, check_dir('~/.skcom'))
    ps_exec(vcdist + r' setup /passive', admin=True)

    # 等待安裝完成
    args = ['tasklist', '/fi', 'imagename eq vcredist_x64.exe', '/fo', 'csv']
    output = cmd_exec(args)
    while output.count('\r\n') == 2:
        time.sleep(0.5)
        output = cmd_exec(args)

    # 移除安裝包
    os.remove(vcdist)

def verof_skcom():
    """
    檢查群益 API 元件是否已註冊
    """
    cmd = r'reg query HKLM\SOFTWARE\Classes\TypeLib /s /f SKCOM.dll'
    result = ps_exec(cmd)

    skcom_ver = '0.0.0.0'
    if result is not None:
        lines = result.split('\r\n')
        for line in lines:
            # 找 DLL 檔案路徑
            match = re.match(r'.+REG_SZ\s+(.+SKCOM.dll)', line)
            if match is not None:
                # 取檔案摘要內容裡版本號碼
                dll_path = match.group(1)
                fso = comtypes.client.CreateObject('Scripting.FileSystemObject')
                try:
                    skcom_ver = fso.GetFileVersion(dll_path)
                    # skcom_ver = fso.GetFileVersion(r'C:\makeexception.txt')
                except COMError:
                    pass

    return version.parse(skcom_ver)

def install_skcom():
    """
    安裝群益 API 元件
    """
    url = 'https://www.capital.com.tw/Service2/download/api_zip/CapitalAPI_2.13.16.zip'

    # 建立元件目錄
    com_path = check_dir(r'~\.skcom\lib')

    # 下載
    file_path = download_file(url, com_path)

    # 解壓縮
    # 只解壓縮 64-bits DLL 檔案, 其他非必要檔案不處理
    # 讀檔時需要用 CP437 編碼處理檔名, 寫檔時需要用 CP950 處理檔名
    with zipfile.ZipFile(file_path, 'r') as archive:
        for name437 in archive.namelist():
            name950 = name437.encode('cp437').decode('cp950')
            if re.match(r'元件/x64/.+\.dll', name950):
                dest_path = r'%s\%s' % (com_path, name950.split('/')[-1])
                with archive.open(name437, 'r') as cmpf, \
                     open(dest_path, 'wb') as extf:
                    extf.write(cmpf.read())

    # 註冊元件
    cmd = r'regsvr32 %s\SKCOM.dll' % com_path
    ps_exec(cmd, admin=True)

    return True

def download_file(url, save_path):
    """
    使用 8K 緩衝下載檔案
    """
    abs_path = check_dir(save_path)
    file_path = r'%s\%s' % (abs_path, url.split('/')[-1])

    with requests.get(url, stream=True) as resp:
        resp.raise_for_status()
        with open(file_path, 'wb') as dlf:
            for chunk in resp.iter_content(chunk_size=8192):
                if chunk:
                    dlf.write(chunk)
            dlf.flush()

    return file_path

def check_dir(usr_path):
    """
    檢查目錄, 不存在就建立目錄, 完成後回傳絕對路徑
    """
    rel_path = os.path.expanduser(usr_path)
    if not os.path.isdir(rel_path):
        os.makedirs(rel_path)
    abs_path = os.path.realpath(rel_path)
    return abs_path