/* Product → item code lookup for store-brief (model code = SC011M.PRD_CD).
   Placeholder: {prd_codes}  e.g. 'ABC123.AKOR', 'XYZ999.AKOR'
*/
SELECT P.PRD_CD   AS 상품코드
     , P.PRD_NM   AS 상품명
     , P.ITEM_ID  AS ITEM_ID
     , C.ITEM_CD  AS 품목코드
  FROM SC011M P
  JOIN SC010C C ON C.ITEM_ID = P.ITEM_ID
 WHERE P.PRD_CD IN ({prd_codes})
