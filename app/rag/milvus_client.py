"""
Milvus 向量数据库客户端

通过 pymilvus 连接本地 Docker 部署的 Milvus 单机版，提供：
- 集合（Collection）管理：创建/获取/删除
- 向量索引管理
- 密集向量检索
- 数据插入

注意：当前阶段 Milvus 连接失败不会阻止系统运行，
系统会自动降级到 MCP 和 LLM 兜底数据源。
"""

from pymilvus import connections, Collection, CollectionSchema, FieldSchema, DataType, utility
from app.config import settings
from app.logger import get_logger

logger = get_logger(__name__)


class MilvusClient:
    """Milvus 客户端封装

    功能：
    - 连接管理（自动重连）
    - 集合创建（含向量索引）
    - 数据插入
    - 向量检索

    使用前需确保 Milvus Docker 容器已启动：
    docker run -d --name milvus-standalone -p 19530:19530 -p 9091:9091 milvusdb/milvus:latest
    """

    def __init__(self):
        self.alias = "default"
        self.host = settings.milvus_host
        self.port = settings.milvus_port
        self.collection_name = settings.milvus_collection
        self.connected = False

    def connect(self):
        """连接到 Milvus 服务

        如果连接失败，设置 connected=False 并记录警告，
        后续操作将自动跳过，不影响整体流程。
        """
        if self.connected:
            return
        try:
            connections.connect(
                alias=self.alias,
                host=self.host,
                port=self.port,
            )
            self.connected = True
            logger.info("Milvus 连接成功: %s:%s", self.host, self.port)
        except Exception as e:
            logger.warning("Milvus 连接失败: %s（系统将使用其他数据源）", e)
            self.connected = False

    def disconnect(self):
        """断开 Milvus 连接"""
        if self.connected:
            connections.disconnect(self.alias)
            self.connected = False
            logger.info("Milvus 已断开连接")

    def create_collection(self, dim: int = 1024):
        """创建商品目录集合

        集合包含密集向量字段和商品属性字段，
        自动创建 IVF_FLAT 向量索引。

        Args:
            dim: 向量维度，需与 Embedding 模型输出维度一致
        """
        self.connect()
        if not self.connected:
            return

        if utility.has_collection(self.collection_name):
            logger.info("集合 %s 已存在，跳过创建", self.collection_name)
            return

        # 定义字段 schema
        fields = [
            FieldSchema(name="id", dtype=DataType.INT64, is_primary=True, auto_id=True),
            FieldSchema(name="product_name", dtype=DataType.VARCHAR, max_length=256),
            FieldSchema(name="platform", dtype=DataType.VARCHAR, max_length=64),
            FieldSchema(name="category", dtype=DataType.VARCHAR, max_length=128),
            FieldSchema(name="price", dtype=DataType.FLOAT),
            FieldSchema(name="sales_volume", dtype=DataType.INT64),
            FieldSchema(name="description", dtype=DataType.VARCHAR, max_length=4096),
            FieldSchema(name="tags", dtype=DataType.VARCHAR, max_length=1024),
            FieldSchema(name="dense_vector", dtype=DataType.FLOAT_VECTOR, dim=dim),
        ]
        schema = CollectionSchema(fields=fields, description="商品向量目录")
        collection = Collection(name=self.collection_name, schema=schema)

        # 创建 IVF_FLAT 索引（平衡检索速度与精度）
        collection.create_index("dense_vector", {
            "index_type": "IVF_FLAT",
            "metric_type": "IP",  # 内积相似度
            "params": {"nlist": 128},
        })

        logger.info("集合 %s 创建完成，向量维度 %d", self.collection_name, dim)

    def get_collection(self) -> Collection | None:
        """获取集合对象

        Returns:
            Collection 对象，连接失败或集合不存在时返回 None
        """
        self.connect()
        if not self.connected:
            return None
        if not utility.has_collection(self.collection_name):
            logger.warning("集合 %s 不存在", self.collection_name)
            return None
        return Collection(self.collection_name)

    def insert(self, entities: list[dict]) -> int | None:
        """插入数据

        Args:
            entities: 数据列表，每项需包含集合中定义的所有字段

        Returns:
            插入的记录数，失败时返回 None
        """
        collection = self.get_collection()
        if collection is None:
            return None
        try:
            mr = collection.insert(entities)
            collection.flush()
            logger.info("插入 %d 条数据到集合 %s", mr.insert_count, self.collection_name)
            return mr.insert_count
        except Exception as e:
            logger.error("数据插入失败: %s", e)
            return None

    def search(self, vector: list[float], top_k: int = 20) -> list[dict]:
        """向量检索

        使用 IVF_FLAT 索引进行近似最近邻搜索。

        Args:
            vector: 查询向量
            top_k: 返回 TOP K 条结果

        Returns:
            检索结果列表，每项包含 id、score 和商品字段
        """
        collection = self.get_collection()
        if collection is None:
            return []

        try:
            collection.load()
            results = collection.search(
                data=[vector],
                anns_field="dense_vector",
                param={"nprobe": 10},
                limit=top_k,
                output_fields=[
                    "product_name", "platform", "category",
                    "price", "sales_volume", "description", "tags",
                ],
            )

            items = []
            for hits in results:
                for hit in hits:
                    items.append({
                        "id": hit.id,
                        "score": hit.score,  # 相似度分数
                        **{k: v for k, v in hit.entity.fields.items() if k != "dense_vector"},
                    })

            logger.debug("Milvus 检索返回 %d 条结果", len(items))
            return items

        except Exception as e:
            logger.error("Milvus 检索失败: %s", e)
            return []


# ==================== 全局单例 ====================

_client: MilvusClient | None = None


def get_milvus_client() -> MilvusClient:
    """获取 Milvus 客户端单例"""
    global _client
    if _client is None:
        logger.info("首次初始化 Milvus 客户端")
        _client = MilvusClient()
    return _client
