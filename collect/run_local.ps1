# run_local.ps1 — phần thu chạy ở MÁY ANH HOÀNG (FB Ad Library + Etsy + SimilarWeb cần Chrome 9230 thật).
# Windows PowerShell 5.1. Task Scheduler gọi lúc 6:05 sáng (lệnh cài: xem collect\README.md).
#   1. Bật Chrome 9230 (profile chrome-cdp-chutan) nếu chưa chạy, chờ tối đa 30 giây.
#   2. git pull --rebase (lấy raw Shopify của GitHub Actions chạy lúc 6:00)
#   3. sync_shops.py  (cập nhật data\shops.json từ kho discover 4-SPY + shops_extra.txt)
#   4. run_local.py   (ads mọi shop Shopify + Etsy trang shop + SimilarWeb ≤ 3 shop)
#   5. build.py       (daily + leaderboard + alerts; lỗi kiểm cấu trúc → không commit)
#   6. git: commit -> pull --rebase -X theirs -> build lại -> commit -> push
# Log: collect\logs\<ngày>.log. Không giết tiến trình nào, không đóng Chrome (cdp.py tự đóng tab của nó).
# File lưu UTF-8 có BOM để PowerShell 5.1 đọc đúng tiếng Việt.

$ErrorActionPreference = 'Continue'
$Here = Split-Path -Parent $MyInvocation.MyCommand.Path
$Root = Split-Path -Parent $Here
$Date = (Get-Date).ToString('yyyy-MM-dd')
$LogDir = Join-Path $Here 'logs'
New-Item -ItemType Directory -Force $LogDir | Out-Null
$Log = Join-Path $LogDir "$Date.log"
$env:PYTHONIOENCODING = 'utf-8'
$ChromeCmd = 'F:\APP BY HOANG\app-hub\scripts\chrome_debug.py'

function Write-Log([string]$msg) {
    $line = "[{0}] {1}" -f (Get-Date).ToString('HH:mm:ss'), $msg
    Add-Content -Path $Log -Value $line -Encoding UTF8
    Write-Host $line
}

# chạy lệnh qua cmd để log giữ đúng UTF-8 (redirect của PS 5.1 ghi UTF-16 và bọc stderr thành lỗi)
function Invoke-Logged([string]$cmdline) {
    Write-Log "> $cmdline"
    cmd /c "$cmdline >> `"$Log`" 2>&1"
    $code = $LASTEXITCODE
    Write-Log "  (mã thoát $code)"
    return $code
}

function Test-Chrome {
    try {
        $r = Invoke-WebRequest -UseBasicParsing -Uri 'http://127.0.0.1:9230/json/version' -TimeoutSec 3
        return ($r.StatusCode -eq 200)
    } catch {
        return $false
    }
}

Write-Log "=== run_local $Date (Root=$Root) ==="
Set-Location $Root

# ---- 1. Chrome 9230
$chromeOk = Test-Chrome
if (-not $chromeOk) {
    Write-Log "Chrome 9230 chưa chạy -> mở bằng chrome_debug.py"
    Start-Process -FilePath 'python' -ArgumentList @("`"$ChromeCmd`"", '9230', 'chrome-cdp-chutan') -WindowStyle Hidden
    for ($i = 0; $i -lt 30; $i++) {
        Start-Sleep -Seconds 1
        if (Test-Chrome) { $chromeOk = $true; break }
    }
}
if ($chromeOk) { Write-Log "Chrome 9230 OK" } else { Write-Log "! Chrome 9230 không lên sau 30s -> bỏ phần thu, vẫn build + push" }

# ---- 2. lấy dữ liệu mới nhất từ GitHub (raw Shopify của Actions)
$pull0 = Invoke-Logged "git pull --rebase --autostash"
if ($pull0 -ne 0) { Write-Log "! git pull đầu lượt lỗi -> vẫn thu, cuối lượt thử lại" }

# ---- 3 + 4. danh sách shop + thu (lỗi phần nào ghi log, chạy tiếp)
$null = Invoke-Logged "python `"$Here\sync_shops.py`""
if ($chromeOk) {
    $null = Invoke-Logged "python `"$Here\run_local.py`" --date $Date"
}

# ---- 5. build
$b = Invoke-Logged "python `"$Here\build.py`""
if ($b -ne 0) { Write-Log "! build lỗi -> KHÔNG commit/push, xem log"; exit 1 }

# ---- 6. git
$null = Invoke-Logged "git add data shops_extra.txt"
cmd /c "git diff --cached --quiet"
if ($LASTEXITCODE -ne 0) {
    $null = Invoke-Logged "git commit -m `"data: $Date local`""
} else {
    Write-Log "Không có thay đổi để commit"
}
# raw mỗi nguồn 1 file nên không xung đột; file tổng hợp có xung đột thì giữ bản local (-X theirs khi rebase) rồi build lại ngay
$pull = Invoke-Logged "git pull --rebase -X theirs"
if ($pull -ne 0) {
    Write-Log "! git pull --rebase lỗi -> huỷ rebase, không push (xem log)"
    $null = Invoke-Logged "git rebase --abort"
    exit 1
}
$b = Invoke-Logged "python `"$Here\build.py`""
if ($b -ne 0) { Write-Log "! build lỗi sau khi gộp -> không push"; exit 1 }
$null = Invoke-Logged "git add data"
cmd /c "git diff --cached --quiet"
if ($LASTEXITCODE -ne 0) {
    $null = Invoke-Logged "git commit -m `"data: $Date local (build lại sau pull)`""
}
$push = Invoke-Logged "git push"
if ($push -ne 0) { Write-Log "! git push lỗi"; exit 1 }
Write-Log "=== xong ==="
exit 0
