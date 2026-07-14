"""雪花 ID 生成器 — 简化版 Snowflake 算法，64 位整数。"""
import time
import threading


class SnowflakeGenerator:
    """简化版雪花算法，生成 64 位整数 ID。

    结构: timestamp(42bit) | datacenter(5bit) | worker(5bit) | sequence(12bit)
    """

    EPOCH = 1577836800000  # 2020-01-01T00:00:00Z (ms)

    def __init__(self, worker_id: int = 1, datacenter_id: int = 1):
        self.worker_id = worker_id & 0x1F
        self.datacenter_id = datacenter_id & 0x1F
        self.sequence = 0
        self.last_timestamp = -1
        self._lock = threading.Lock()

    def next_id(self) -> int:
        with self._lock:
            timestamp = int(time.time() * 1000)
            if timestamp < self.last_timestamp:
                timestamp = self.last_timestamp

            if timestamp == self.last_timestamp:
                self.sequence = (self.sequence + 1) & 0xFFF
                if self.sequence == 0:
                    while timestamp <= self.last_timestamp:
                        timestamp = int(time.time() * 1000)
            else:
                self.sequence = 0

            self.last_timestamp = timestamp
            return (
                ((timestamp - self.EPOCH) << 22)
                | (self.datacenter_id << 17)
                | (self.worker_id << 12)
                | self.sequence
            )


def generate_snowflake_ids(
    entities: list[dict],
) -> dict[str, int]:
    """为实体中由 LLM 生成的 id 分配雪花 ID，相同随机串 → 相同雪花 ID。

    雪花算法保证全局唯一，无需查库去重校验。
    仅处理实体的 properties.id，不涉及关系的 start_node_id/end_node_id。

    Returns:
        {original_id_str: snowflake_int} 映射表
    """
    random_ids: set[str] = set()
    for ent in entities:
        eid = (ent.get("properties", {}).get("id") or "").strip()
        if not eid:
            continue
        if eid.isdigit() or eid == "大模型随机生成":
            continue
        random_ids.add(eid)

    if not random_ids:
        return {}

    sf = SnowflakeGenerator(worker_id=1, datacenter_id=1)
    id_map: dict[str, int] = {}
    for rid in random_ids:
        id_map[rid] = sf.next_id()

    return id_map
