from src.services.collector import TelemetryCollector                                   
from src.services.snowflake_client import SnowflakeClient                               
from src.services.watermark_manager import WatermarkManager                             
                                                                                            
def main():                                                                             
    # 1. Initialize dependencies                                                        
    client = SnowflakeClient()                                                          
    wm = WatermarkManager()
        
        # 2. Instantiate the collector with its dependencies
    collector = TelemetryCollector(client=client, watermark_manager=wm)
        
        # 3. Call the method on the instance
    snapshots = collector.collect_snapshots()
        
    print(f"Collected {len(snapshots)} snapshots!")
        
        # Optionally, print the first one to verify
    if snapshots:
        print(snapshots[0].model_dump_json(indent=2))
  
if __name__ == "__main__":
    main()