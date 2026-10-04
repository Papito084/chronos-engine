"""
ChronosEngine - Redpanda Topic Provisioner.
Creates 'market.commands' and 'market.events' with deterministic configuration.
"""

import asyncio
from aiokafka.admin import AIOKafkaAdminClient, NewTopic


async def provision_topics(bootstrap_servers: str = "localhost:9092"):
    print(f"Connecting to Redpanda at {bootstrap_servers}...")
    admin = AIOKafkaAdminClient(bootstrap_servers=bootstrap_servers)
    await admin.start()
    try:
        existing_topics = await admin.list_topics()
        print(f"Existing topics: {existing_topics}")

        topics_to_create = []
        if "market.commands" not in existing_topics:
            topics_to_create.append(
                NewTopic(
                    name="market.commands",
                    num_partitions=4,
                    replication_factor=1,
                    topic_configs={
                        "cleanup.policy": "delete",
                        "retention.ms": "86400000",  # 24h
                    },
                )
            )

        if "market.events" not in existing_topics:
            topics_to_create.append(
                NewTopic(
                    name="market.events",
                    num_partitions=1,  # Strict monotonic global order per market instance
                    replication_factor=1,
                    topic_configs={
                        "cleanup.policy": "compact",
                        "segment.ms": "60000",
                    },
                )
            )

        if topics_to_create:
            print(f"Creating topics: {[t.name for t in topics_to_create]}")
            await admin.create_topics(new_topics=topics_to_create)
            print("Topics created successfully.")
        else:
            print("All required topics already exist.")
    finally:
        await admin.close()


if __name__ == "__main__":
    asyncio.run(provision_topics())
