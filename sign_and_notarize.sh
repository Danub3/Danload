#!/bin/bash
# sign_and_notarize.sh — Danload macOS 签名、公证、DMG 打包脚本
#
# 使用前请先填写以下变量，然后运行：
#   chmod +x sign_and_notarize.sh
#   ./sign_and_notarize.sh
#
# 前提：
#   1. Xcode Command Line Tools 已安装
#   2. Developer ID Application 证书已导入 Keychain
#   3. 已在 App Store Connect 生成「App 专用密码」用于公证
#      （https://appleid.apple.com → 安全 → App 专用密码）

# ─── 配置（必填）────────────────────────────────────────────────────────────

# Developer ID Application 证书全名（在 Keychain Access 中查看）
SIGN_IDENTITY="Developer ID Application: Yao Junran (MG6J934ARX)"

# Apple ID 邮箱（用于公证）
APPLE_ID="2270624076@qq.com"

# Team ID（10 位字符，Developer 账户页面查看）
TEAM_ID="MG6J934ARX"

# App 专用密码（在 appleid.apple.com 生成，格式 xxxx-xxxx-xxxx-xxxx）
APP_PASSWORD="nfek-cqdh-uflt-gwxc"

# ─── 路径配置（通常不需要修改）─────────────────────────────────────────────

APP_NAME="Danload"
APP_PATH="dist/${APP_NAME}.app"
VERSION=$(defaults read "$(pwd)/${APP_PATH}/Contents/Info" CFBundleShortVersionString)
DMG_NAME="${APP_NAME}-${VERSION}.dmg"
DMG_OUTPUT="dist/${DMG_NAME}"

# ─── 脚本开始 ────────────────────────────────────────────────────────────────

set -e  # 任何步骤失败立即退出

echo "==> [1/5] 签名 .app..."
codesign \
    --deep \
    --force \
    --verify \
    --verbose \
    --sign "${SIGN_IDENTITY}" \
    --options runtime \
    --entitlements entitlements.plist \
    "${APP_PATH}"

echo "==> [2/5] 验证签名..."
codesign --verify --deep --strict --verbose=2 "${APP_PATH}"

echo "==> [3/5] 打包成 .dmg..."
mkdir -p dist
# 删除旧的 dmg（如果存在）
[ -f "${DMG_OUTPUT}" ] && rm "${DMG_OUTPUT}"
hdiutil create \
    -volname "Danload" \
    -srcfolder "${APP_PATH}" \
    -ov \
    -format UDZO \
    "${DMG_OUTPUT}"

echo "==> [3.5/5] 签名 .dmg..."
codesign \
    --sign "${SIGN_IDENTITY}" \
    --verbose \
    "${DMG_OUTPUT}"

echo "==> [4/5] 提交公证（等待 Apple 审核，通常 1-5 分钟）..."
xcrun notarytool submit "${DMG_OUTPUT}" \
    --apple-id "${APPLE_ID}" \
    --team-id "${TEAM_ID}" \
    --password "${APP_PASSWORD}" \
    --wait

echo "==> [5/5] 钉上公证票据（staple）..."
xcrun stapler staple "${DMG_OUTPUT}"
xcrun stapler validate "${DMG_OUTPUT}"

echo "==> [6/6] 验证 Gatekeeper..."
spctl --assess --type execute --verbose "${APP_PATH}"

echo ""
echo "✅ 完成！分发文件：${DMG_OUTPUT}"
