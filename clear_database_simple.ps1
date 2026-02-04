# 清空数据库脚本（PowerShell 版本，无需 Python）
# 使用方法：右键点击此文件 -> "使用 PowerShell 运行"

Write-Host "============================================================" -ForegroundColor Cyan
Write-Host "   清空数据库脚本" -ForegroundColor Cyan
Write-Host "============================================================" -ForegroundColor Cyan
Write-Host ""
Write-Host "⚠️  警告：此操作将删除以下数据：" -ForegroundColor Yellow
Write-Host "  - 所有音频文件记录"
Write-Host "  - 所有项目数据"
Write-Host "  - 所有索引文件"
Write-Host "  - 所有缓存文件"
Write-Host "  - 所有备份文件"
Write-Host ""
Write-Host "✅  以下数据将被保留：" -ForegroundColor Green
Write-Host "  - AI 模型文件（data/models/）"
Write-Host ""

$confirm = Read-Host "确认要继续吗？(输入 'yes' 继续)"
if ($confirm -ne "yes") {
    Write-Host "操作已取消" -ForegroundColor Yellow
    exit
}

Write-Host ""
Write-Host "开始清理..." -ForegroundColor Green
Write-Host ""

$scriptPath = Split-Path -Parent $MyInvocation.MyCommand.Path
$projectRoot = Split-Path -Parent $scriptPath
$dataDir = Join-Path $projectRoot "data"

# 1. 删除数据库文件
$dbDir = Join-Path $dataDir "database"
if (Test-Path $dbDir) {
    $dbFiles = Get-ChildItem -Path $dbDir -Filter "*.db*" -File
    foreach ($file in $dbFiles) {
        try {
            Remove-Item $file.FullName -Force
            Write-Host "✓ 已删除数据库文件: $($file.Name)" -ForegroundColor Green
        } catch {
            Write-Host "✗ 删除数据库文件失败 $($file.Name): $_" -ForegroundColor Red
        }
    }
    if ($dbFiles.Count -eq 0) {
        Write-Host "ℹ 未找到数据库文件（可能已经清空）" -ForegroundColor Gray
    }
} else {
    Write-Host "ℹ 数据库目录不存在" -ForegroundColor Gray
}

# 2. 清空索引目录
$indexDir = Join-Path $dataDir "index"
if (Test-Path $indexDir) {
    try {
        Get-ChildItem -Path $indexDir -Recurse | Remove-Item -Force -Recurse
        Write-Host "✓ 索引目录已清空: $indexDir" -ForegroundColor Green
    } catch {
        Write-Host "✗ 清空索引目录失败: $_" -ForegroundColor Red
    }
} else {
    Write-Host "ℹ 索引目录不存在" -ForegroundColor Gray
}

# 3. 清空缓存目录
$cacheDir = Join-Path $dataDir "cache"
if (Test-Path $cacheDir) {
    try {
        Get-ChildItem -Path $cacheDir -Recurse | Remove-Item -Force -Recurse
        Write-Host "✓ 缓存目录已清空: $cacheDir" -ForegroundColor Green
    } catch {
        Write-Host "✗ 清空缓存目录失败: $_" -ForegroundColor Red
    }
} else {
    Write-Host "ℹ 缓存目录不存在" -ForegroundColor Gray
}

# 4. 清空项目目录
$projectsDir = Join-Path $dataDir "projects"
if (Test-Path $projectsDir) {
    try {
        Get-ChildItem -Path $projectsDir -Recurse | Remove-Item -Force -Recurse
        Write-Host "✓ 项目目录已清空: $projectsDir" -ForegroundColor Green
    } catch {
        Write-Host "✗ 清空项目目录失败: $_" -ForegroundColor Red
    }
} else {
    Write-Host "ℹ 项目目录不存在" -ForegroundColor Gray
}

# 5. 清空备份目录
$backupsDir = Join-Path $dataDir "backups"
if (Test-Path $backupsDir) {
    try {
        Get-ChildItem -Path $backupsDir -Recurse | Remove-Item -Force -Recurse
        Write-Host "✓ 备份目录已清空: $backupsDir" -ForegroundColor Green
    } catch {
        Write-Host "✗ 清空备份目录失败: $_" -ForegroundColor Red
    }
} else {
    Write-Host "ℹ 备份目录不存在" -ForegroundColor Gray
}

# 6. 确保必要的目录存在
$dirs = @($dbDir, $indexDir, $cacheDir, $projectsDir, $backupsDir)
foreach ($dir in $dirs) {
    if (-not (Test-Path $dir)) {
        New-Item -ItemType Directory -Path $dir -Force | Out-Null
    }
    $gitkeep = Join-Path $dir ".gitkeep"
    if (-not (Test-Path $gitkeep)) {
        New-Item -ItemType File -Path $gitkeep -Force | Out-Null
    }
}
Write-Host "✓ 必要的目录结构已重建" -ForegroundColor Green

Write-Host ""
Write-Host "============================================================" -ForegroundColor Cyan
Write-Host "✅ 清理完成！" -ForegroundColor Green
Write-Host "============================================================" -ForegroundColor Cyan
Write-Host ""
Write-Host "已清空的内容："
Write-Host "  - 数据库文件"
Write-Host "  - 索引文件"
Write-Host "  - 缓存文件"
Write-Host "  - 项目文件"
Write-Host "  - 备份文件"
Write-Host ""
Write-Host "已保留的内容："
Write-Host "  - AI 模型文件（data/models/）" -ForegroundColor Green
Write-Host ""
Write-Host "💡 提示：请重启应用程序以使用全新的数据库" -ForegroundColor Yellow
Write-Host ""
Read-Host "按 Enter 键退出"
