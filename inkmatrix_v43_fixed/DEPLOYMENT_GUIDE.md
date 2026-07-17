# 墨算系统 v4.2.0 - 部署和使用指南

## 📦 部署前准备

### 系统要求
```
操作系统：Windows 7+ / macOS 10.12+ / Linux (Ubuntu 16.04+)
Python版本：3.7+
内存：≥ 512MB
磁盘空间：≥ 1GB（包括数据库）
```

### 依赖包安装
```bash
cd inkmatrix_v42_final
pip install -r requirements.txt
```

**requirements.txt 内容**：
```
numpy>=1.20.0
scipy>=1.6.0
PyQt5>=5.15.0        # 如果使用Qt5 GUI
pandas>=1.2.0         # 数据处理
Pillow>=8.0.0         # 图像处理
requests>=2.26.0      # 更新下载
```

---

## 🚀 快速启动

### 第一次运行

```bash
# 1. 进入项目目录
cd inkmatrix_v42_final

# 2. 初始化系统（创建必要的目录和配置）
python main.py --init

# 3. 创建默认admin账户（仅第一次需要）
python main.py --create-admin --username admin --password <your_secure_password>

# 4. 启动应用
python main.py
```

### 后续运行
```bash
python main.py
```

---

## 🔐 账户管理

### 初始化admin账户
```bash
python main.py --create-admin \
  --username admin \
  --password your_secure_password \
  --display-name "系统管理员"
```

### 创建其他账户
```bash
# 创建卖家账户
python main.py --create-account \
  --username seller001 \
  --password password123 \
  --display-name "张三油墨店" \
  --type seller

# 创建普通用户账户
python main.py --create-account \
  --username user001 \
  --password password123 \
  --display-name "李四" \
  --type user
```

### 管理账户权限
在应用中：
```
管理 → 用户管理 → 选择用户 → 编辑权限
```

或命令行：
```bash
python main.py --set-permission \
  --username seller001 \
  --permission can_edit_ink_library \
  --value true
```

---

## 💾 数据备份和恢复

### 自动备份
系统默认每小时自动创建备份，保存在 `./backups` 目录。

### 手动备份
```bash
python -m hal_layer.update_backup_service --list-backups
```

### 备份恢复
```bash
# 列出所有备份
python -m hal_layer.update_backup_service --list-backups

# 恢复指定备份
python -m hal_layer.update_backup_service \
  --restore-backup backup_2024-07-16_140000
```

### 紧急数据导出
```bash
# 导出数据库（即使应用无法启动也能使用）
python -m hal_layer.update_backup_service \
  --export-db data/ \
  --export-to ./safe_location
```

---

## 🔄 更新系统

### 手动检查更新
```bash
python main.py --check-updates
```

### 通过UI更新
```
帮助 → 检查更新 → 显示更新信息 → 点击"下载和安装"
```

系统会自动：
1. ✓ 备份当前版本到 `./backups`
2. ✓ 下载最新版本
3. ✓ 验证文件完整性
4. ✓ 安装新版本
5. ✓ 提示重启

用户数据和配置完全保留。

### 版本回退
如果需要回退到之前的版本：
```bash
python -m hal_layer.update_backup_service \
  --restore-backup backup_v4.1.0_xxxxx
python main.py --migrate-from v4.1.0
```

---

## ⚙️ 配置调整

### 修改配置文件
编辑 `config/system_config_v42.json`：

```json
{
  "performance_settings": {
    "cache_ttl_seconds": 3600,  // 缓存有效期（秒）
    "async_loading_enabled": true,  // 异步加载
    "ui_update_debounce_ms": 200  // UI更新去抖动（毫秒）
  },
  "color_engine_settings": {
    "optimization_level_default": "high",  // standard/high/critical
    "hue_deviation_threshold_degrees": 45  // 色相离谱阈值
  }
}
```

### 重载配置
```bash
python main.py --reload-config
```

---

## 🧪 系统检查和诊断

### 运行自诊断
```bash
python main.py --diagnose
```

输出示例：
```
=== 系统诊断报告 ===

✓ Python版本：3.9.7
✓ 依赖包：已齐备
✓ 数据库文件：OK
✓ 备份系统：运行中，最后备份时间 2024-07-16 14:00:00
✓ 权限系统：正常
✓ 缓存系统：100个项目，内存占用 12MB
✓ 性能指标：平均响应 87ms

⚠ 警告：日志文件超过100MB，建议清理
```

### 查看性能报告
```bash
python main.py --performance-report
```

输出示例：
```
=== 性能监控报告 ===

load_ink_database: 平均2.3s, 最后2.1s, 最大3.5s
match_color: 平均450ms, 最后320ms, 最大1200ms
save_print_job: 平均150ms, 最后140ms, 最大300ms
ui_render: 平均45ms, 最后42ms, 最大120ms
```

### 清理日志和缓存
```bash
# 清理缓存
python main.py --clear-cache

# 清理旧日志（保留最近7天）
python main.py --cleanup-logs --days 7

# 清理旧备份（保留最近5个）
python main.py --cleanup-backups --keep 5
```

---

## 📊 使用示例

### 示例1：快速配色工作流

```
1. 登录 → 输入admin/password
2. 打开 工作台 → 印刷工单
3. 上传或输入目标色 (RGB或Pantone)
4. 系统显示配方：
   ├─ 油墨配比
   ├─ 预计颜色（可视化）
   ├─ 色差（ΔE94 = 1.5）
   ├─ 使用的油墨数（4种）
   └─ 成本评分
5. 点击"生成工单" → 打印或导出
```

### 示例2：多账户油墨库管理

```
账户A（卖家）：
├─ 库存：Cyan 100ml, Magenta 50ml, ...
├─ 权限：可编辑自己的油墨库
└─ 查看：只能看自己和系统标准油墨

账户B（普通用户）：
├─ 库存：无
├─ 权限：只能查看已发布油墨
└─ 行为：可以使用配色系统

两个账户的数据完全隔离 ✓
```

### 示例3：备份和恢复

```
场景：应用意外崩溃

步骤1（自动进行）：
  • 后台备份系统已经保存了最近的数据
  • 位置：./backups/backup_2024-07-16_140000

步骤2（重启应用）：
  • 应用检测到上次异常退出
  • 弹窗提示"是否恢复上次的工作"

步骤3（用户选择）：
  • 点击"恢复"
  • 数据恢复到备份时间点
  • 应用继续运行

全程零数据丢失 ✓
```

---

## 🚨 常见问题排查

### Q1：应用启动很慢
**解决**：
```bash
# 清理缓存（可能缓存数据过多）
python main.py --clear-cache

# 检查性能
python main.py --diagnose

# 如果还是慢，可以增加缓存大小
编辑 config/system_config_v42.json:
  cache_ttl_seconds: 7200  # 增加到2小时
```

### Q2：配色结果不准确
**解决**：
```bash
# 1. 检查油墨库是否完整
管理 → 油墨库 → 检查数据完整性

# 2. 尝试高级优化模式
工作台 → 高级选项 → 优化级别: critical

# 3. 查看是否有警告信息
配方结果下方的"⚠️ 提示"部分
```

### Q3：备份文件很大
**解决**：
```bash
# 清理旧备份
python main.py --cleanup-backups --keep 5

# 或者修改备份策略
编辑 config/system_config_v42.json:
  max_backup_count: 5  # 只保留5个
  backup_interval_seconds: 86400  # 改为每天备份一次
```

### Q4：权限问题 - 无法编辑油墨库
**解决**：
```bash
# 检查用户权限
管理 → 用户管理 → 选择用户 → 查看权限

# 赋予权限
☑ 编辑油墨档案
☑ 导入油墨
☑ 载入标准专色库
☑ 新增油墨档案
☑ 删除选中油墨

# 保存
```

### Q5：界面显示有问题（选中项看不清）
**解决**：
```bash
# 检查UI主题设置
编辑 config/system_config_v42.json:
  "selection_color": "#3B82F6"      # 选中色（蓝色）
  "selection_background": "#EFF6FF"  # 选中背景（超浅蓝）

# 如果自定义了，建议恢复默认值
```

### Q6：系统崩溃，需要恢复数据
**解决**：
```bash
# 步骤1：列出所有备份
python -m hal_layer.update_backup_service --list-backups

# 步骤2：选择要恢复的备份
python -m hal_layer.update_backup_service \
  --restore-backup backup_2024-07-16_140000

# 步骤3：重启应用
python main.py
```

---

## 📈 性能优化建议

### 对于小型工作室（< 1000个工单/月）
```json
{
  "cache_ttl_seconds": 3600,
  "async_loading_enabled": true,
  "max_backup_count": 10,
  "backup_interval_seconds": 3600
}
```

### 对于中型工厂（1000-10000个工单/月）
```json
{
  "cache_ttl_seconds": 7200,
  "async_loading_enabled": true,
  "query_cache_ttl": 120,
  "max_backup_count": 20,
  "backup_interval_seconds": 1800
}
```

### 对于大型印刷厂（> 10000个工单/月）
```json
{
  "cache_ttl_seconds": 14400,
  "async_loading_enabled": true,
  "batch_size": 200,
  "query_cache_ttl": 300,
  "max_backup_count": 30,
  "backup_interval_seconds": 900,
  "log_level": "WARNING"  // 减少日志I/O
}
```

---

## 🔗 集成和扩展

### 与ERP系统集成
```python
# 导入工单接口
from dal_layer.data_manager import ImportPrintJobAPI

api = ImportPrintJobAPI()
api.import_from_erp(erp_host, erp_port, api_key)
```

### 导出配方到生产系统
```python
# 导出接口
api.export_formula(formula_id, target_system='PrinterAPI')

# 支持的目标系统：
# - PrinterAPI (直接连接打印机)
# - MESSystem (制造执行系统)
# - CSVFormat (CSV文件导出)
# - ExcelFormat (Excel文件导出)
```

### 自定义油墨库导入
```python
# 导入自定义油墨库
from core_layer.ink_import import InkImporter

importer = InkImporter()
importer.import_from_csv('my_inks.csv')
importer.import_from_spectral_data('spectral_data.txt')
```

---

## 📞 技术支持

### 获取日志文件
```bash
# 日志位置
./logs/inkmatrix.log

# 查看最后100行
tail -n 100 logs/inkmatrix.log

# 查看特定时间的错误
grep "ERROR" logs/inkmatrix.log | grep "2024-07-16 14"
```

### 生成诊断报告
```bash
python main.py --diagnose > diagnostic_report.txt

# 包含内容：
# - 系统配置
# - 依赖包版本
# - 数据库状态
# - 备份情况
# - 性能指标
# - 错误日志摘要
```

### 联系支持团队
- 文档：https://docs.inkmatrix.local
- 邮件：support@inkmatrix.local
- 电话：+86-10-xxxx-xxxx
- 反馈：https://feedback.inkmatrix.local

---

## ✅ 升级检查清单

升级前：
- [ ] 备份所有数据
- [ ] 记录当前版本号
- [ ] 关闭所有用户连接
- [ ] 检查磁盘空间

升级中：
- [ ] 运行更新程序
- [ ] 等待数据迁移完成
- [ ] 验证文件完整性

升级后：
- [ ] 验证应用启动
- [ ] 检查数据完整性
- [ ] 测试核心功能
- [ ] 查看错误日志
- [ ] 确认备份恢复成功

---

**系统已准备好投入生产使用！祝您使用愉快！** 🎉
