# Execution Log: Task-002

## 使用的 Playbook
- [practice-001] 应用方式: 生成 hello_world_2.py 至 hello_world_20.py 时让文件名与输出编号严格一致，入口只打印对应编号。
- [practice-002] 应用方式: 通过批量运行 20 个脚本比对输出与编号，发现问题则退出。
- [anti-001] 避免方式: 每个脚本只保留单个 print 调用，确保没有多余编号输出。

## 代码实现
### `hello_world_2.py`
```python
"""Script that prints hello world 2."""


def main() -> None:
    print("hello world 2")


if __name__ == "__main__":
    main()
```
其余 `hello_world_3.py` 至 `hello_world_20.py` 结构一致，仅编号随文件名递增。

## 执行证据
### 构建检查
- Command: 无需构建
- Result: 通过

### 验证测试
- Command:
  ```powershell
  @'
  import subprocess, sys, pathlib

  root = pathlib.Path(r"\\?\D:\Repo\prompt\ACE\test1")
  failures = []
  outputs = []
  for n in range(1, 21):
      path = root / f"hello_world_{n}.py"
      proc = subprocess.run([sys.executable, str(path)], capture_output=True, text=True)
      stdout = proc.stdout.strip()
      stderr = proc.stderr.strip()
      outputs.append((n, stdout, proc.returncode, stderr))
      expected = f"hello world {n}"
      if stdout != expected or proc.returncode != 0 or stderr:
          failures.append((n, expected, stdout, proc.returncode, stderr))

  if failures:
      for n, exp, out, rc, err in failures:
          print(f"[FAIL] hello_world_{n}.py expected '{exp}' got '{out}' rc={rc} err='{err}'")
      sys.exit(1)

  for n, out, rc, err in outputs:
      print(f"[OK] hello_world_{n}.py -> '{out}'")
  '@ | python -
  ```
- Result: 通过

## 验收核对
- [x] 条件1: 已存在 hello_world_1.py 至 hello_world_20.py 共 20 个脚本
- [x] 条件2: 每个脚本仅输出一行 `hello world <N>` 且编号与文件名一致
- [x] 条件3: 批量执行验证全部通过

## 总结
- **结果:** SUCCESS
- **问题:** 无
