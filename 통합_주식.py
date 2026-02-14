import pandas as pd
from datetime import datetime
import openpyxl

# 엑셀 파일 읽기
excel_file = pd.ExcelFile('주식.xlsx')

# 통합할 데이터를 저장할 리스트
all_data = []

print("시트 통합 중...")

for sheet_name in excel_file.sheet_names:
    # 각 시트 읽기
    df = pd.read_excel(excel_file, sheet_name=sheet_name)

    # 날짜 파싱
    try:
        # 다양한 형식 처리 (YYYYMMDD, YYYYMMDDHHmm 등)
        if len(sheet_name) == 8:  # YYYYMMDD
            date = datetime.strptime(sheet_name, '%Y%m%d')
        elif len(sheet_name) == 12:  # YYYYMMDDHHmm
            date = datetime.strptime(sheet_name, '%Y%m%d%H%M')
        else:
            print(f"경고: '{sheet_name}' 시트의 날짜 형식을 파싱할 수 없습니다.")
            continue
    except Exception as e:
        print(f"경고: '{sheet_name}' 시트 처리 중 오류 발생: {e}")
        continue

    # 날짜 컬럼 추가
    df.insert(0, '날짜', date)

    # 컬럼명 통일 (상품명 -> 종목명)
    if '상품명' in df.columns:
        df.rename(columns={'상품명': '종목명'}, inplace=True)

    all_data.append(df)
    print(f"  ✓ {sheet_name} 처리 완료")

# 모든 데이터 통합
combined_df = pd.concat(all_data, ignore_index=True)

# 날짜순으로 정렬
combined_df.sort_values('날짜', inplace=True)

# 컬럼 순서 정리 (날짜, 종목명을 앞으로)
cols = combined_df.columns.tolist()
if '종목명' in cols:
    cols.remove('종목명')
    cols.insert(1, '종목명')
combined_df = combined_df[cols]

print(f"\n통합 완료!")
print(f"총 {len(combined_df)}개 행 통합")
print(f"\n통합된 데이터 미리보기:")
print(combined_df.head(10))

# 새 엑셀 파일로 저장
output_file = '주식_통합.xlsx'
combined_df.to_excel(output_file, sheet_name='통합데이터', index=False, engine='openpyxl')

print(f"\n'{output_file}' 파일로 저장되었습니다.")

# 기본 통계 출력
print("\n=== 데이터 요약 ===")
print(f"기간: {combined_df['날짜'].min().strftime('%Y-%m-%d')} ~ {combined_df['날짜'].max().strftime('%Y-%m-%d')}")
print(f"총 기록 수: {len(combined_df)}")
print(f"\n종목별 기록 수:")
if '종목명' in combined_df.columns:
    print(combined_df['종목명'].value_counts().head(10))
