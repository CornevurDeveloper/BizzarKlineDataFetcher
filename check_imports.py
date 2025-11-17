# check_imports.py
import sys
import os

def check_imports():
    """Проверяет все импорты проекта"""
    
    print("🔍 Проверка импортов...\n")
    print(f"Python: {sys.version}")
    print(f"Рабочая директория: {os.getcwd()}")
    print(f"sys.path[0]: {sys.path[0]}\n")
    
    errors = []
    
    # Проверяем корневые модули
    try:
        import config
        print("✅ config")
    except ImportError as e:
        errors.append(f"❌ config: {e}")
    
    try:
        import api_parser
        print("✅ api_parser")
    except ImportError as e:
        errors.append(f"❌ api_parser: {e}")
    
    # Проверяем пакет data_collector
    try:
        import data_collector.task_builder
        print("✅ data_collector.task_builder")
    except ImportError as e:
        errors.append(f"❌ data_collector.task_builder: {e}")
    
    try:
        import data_collector.fetch_strategies
        print("✅ data_collector.fetch_strategies")
    except ImportError as e:
        errors.append(f"❌ data_collector.fetch_strategies: {e}")
    
    try:
        import data_collector.data_processing
        print("✅ data_collector.data_processing")
    except ImportError as e:
        errors.append(f"❌ data_collector.data_processing: {e}")
    
    try:
        from data_collector.coin_source import get_coins
        print("✅ data_collector.coin_source.get_coins")
    except ImportError as e:
        errors.append(f"❌ data_collector.coin_source: {e}")
    
    # Итоговый отчёт
    print("\n" + "="*50)
    if errors:
        print("💥 НАЙДЕНЫ ОШИБКИ:")
        for err in errors:
            print(f"  {err}")
        return False
    else:
        print("🎉 ВСЕ ИМПОРТЫ РАБОТАЮТ!")
        return True

if __name__ == "__main__":
    success = check_imports()
    sys.exit(0 if success else 1)