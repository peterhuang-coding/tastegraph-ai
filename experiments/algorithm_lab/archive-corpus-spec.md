# 图源元数据分层年代标注评测规格（30条，定向修正版）

## 一、规范与输入假设分离

**Schema规范**只定义字段、取值、证据等级；**输入假设**只描述本批30条可见材料，二者不得互相证明。

### 1. 五个年代层

- `photo_created`：照片拍摄日期/年份。仅当单图材料明确指向拍摄时填写；未知为 `null`。
- `depicted_date`：画面事件、人物活动、场景或物件所属时间。**不得默认复制** `photo_created`；只有材料支持“拍下时即该活动发生时”才可同值。
- `series_context_date`：与系列相关的上下文时间，须再用子类型说明。本批 Owens 仅有 `foreword_date=Summer 1972`，**不是系列创作年、完成年或出版年**；`series_creation_date=null`。
- `published_date`：当前网页或纸本/栏目的首次刊载日期。未见可靠著录时为 `null`；**HTTP Last-Modified 只能代表文件/响应相关时间，不能当首次刊载**。
- `collected_date`：研究方采集/入库时间。本批脱敏数据**未提供**，因此评测值为 `null`；不能表述为“现实中从未记录”。

日期可标准化为 `YYYY`、`YYYY-MM-DD`；季节保留 `1972 summer`，不得伪造月日。配套字段：`precision=day/month/year/season/decade/unknown`、`uncertainty`、`evidence_level`、`evidence_text`、`layer`、`location`、`rights_status`。

证据等级：A=单图/单页明写且作用域清楚；B=系列/期次上下文明写；C=文件名、URL、路径等技术线索；D=无证据。

## 二、四组结论

### Owens（8条）

- **可确认**：Suburbia 页面/证据称原书前言落款 “Summer 1972”。可存为 `foreword_date`，层级属系列/文献上下文，证据级B。
- **不可确认**：各单图拍摄日、系列创作起止、首次刊载时间、本批脱敏数据的采集时间、许可范围。
- **Gold要求**：`photo_created=null`、`series_creation_date=null`、`foreword_date="1972 summer"`、`published_date=null`、`collected_date=null`。
- **约束**：不能把前言1972赋给每图；图片URL中的 `2023/02` 只是路径，不作年代金标准。

### Shabazz（6条）

- **可确认**：单图题注分别给出1980、1981、1997、2003、2005，并含 Brooklyn、Chicago、Harlem、New York 等地点。
- **不可确认**：月日、当前网页首发日期、脱敏采集日期、授权范围。
- **Gold要求**：题注明确作品年份时，`photo_created=YYYY`、精度year、A级；`depicted_date` 须由标注员根据题注语义另行确认，不机械复制。地点入独立字段。
- **约束**：不得用统一URL路径 `2016/06` 覆盖题注年份；不得把不同城市、年份压成同一系列年。Courtesy 仅映射“公开展示/由艺术家提供；许可未确认”。

### PARCO ACROSS（8条）

- **可确认**：可见证据称“PARCO ACROSS 第175回，1995/07/01”，具体页面对应各图；可规范为 `1995-07-01`。
- **不可确认**：当前输入不能单独证明每张均在当日实拍；当前网页上线日、脱敏采集日期、许可。
- **Gold要求**：这是“定点观察期次”样本，应填 `observation_round_date=1995-07-01`，可与 `published_date` 分开。输入既有 `photo_created=1995-07-01` 属当前编辑推断，不得静默当真值；应在 `uncertainty` 中注明“期次日是否等于拍摄日未由题注证明”，严格模式下 `photo_created=null`。
- **约束**：日文 caption 本身无日期；“最近”“1〜2年前”是相对表述，不推绝对年份。

### Hugh Holland（8条）

- **可确认**：单图题注明写1975或1976；系列路径名为 `1970's-color`。
- **不可确认**：月日、网页首发日、脱敏采集日期、许可。
- **Gold要求**：单图 `photo_created=1975/1976`，A级；`depicted_date` 需独立判定。系列路径只能产生C级候选标签 `series_label="1970s color"`，**不能作为年代证据金标准**；若机构页面另有明确系列年代著录才可升为A/B。

## 三、恰好8个复用案例

1. **owens / 1**
   image_url: https://www.billowens.com/wp-content/uploads/2023/02/suburbia-1.jpg
   source_url: https://www.billowens.com/photographs/suburbia
   Gold：`foreword_date="1972 summer"`；`photo_created=null`；2023不采信。

2. **owens / 8**
   image_url: https://www.billowens.com/wp-content/uploads/2023/02/suburbia-12.jpg
   source_url: https://www.billowens.com/photographs/suburbia
   Gold：前言时间仅属文献上下文；系列创作、刊载、采集均未知。

3. **shabazz / 1**
   image_url: https://aperture.org/wp-content/uploads/2016/06/School-Days.-Brooklyn-NY-1981.jpg
   source_url: https://aperture.org/editorial/vision-justice-jamel-shabazz/
   Gold：Brooklyn，1981；URL的2016不采用。

4. **shabazz / 2**
   image_url: https://aperture.org/wp-content/uploads/2016/06/223MAG047_Shabazz-HR.jpg
   source_url: https://aperture.org/editorial/vision-justice-jamel-shabazz/
   Gold：Chicago, Illinois，1997；测试无年份文件名。

5. **shabazz / 4**
   image_url: https://aperture.org/wp-content/uploads/2016/06/223MAG392_Shabazz-HR.jpg
   source_url: https://aperture.org/editorial/vision-justice-jamel-shabazz/
   Gold：New York，2005；防止系列单年化。

6. **across / 1**
   image_url: https://www.web-across.com/observe/srnrj2000003f9vl-img/srnrj2000003f9x7.jpg
   source_url: https://www.web-across.com/observe/srnrj2000003f9vl.html
   Gold：期次/定点观察日期1995-07-01；拍摄日期不确定。

7. **across / 8**
   image_url: https://www.web-across.com/observe/srnrj2000003faf5-img/srnrj2000003fagr.jpg
   source_url: https://www.web-across.com/observe/srnrj2000003faf5.html
   Gold：“1〜2年前”“最近”不得转绝对年份。

8. **holland / 5**
   image_url: https://static-assets.artlogic.net/w_980,h_525,c_limit,f_auto,fl_lossy/artlogicstorage/mbla/images/view/d260820eb4c53b1cac41c1d587c32397ff4aa19e.jpg
   source_url: https://www.mbphoto.com/artists/16/series/1970%27s-color/11350/
   Gold：题注单图1975；URL的1970s仅为候选系列标签。

## 四、Regex失效测试设计

冻结30条样本，**人工gold表与机器预测表分离**；不实现或修改原型，不称已新爬取，不称许可确认。

Gold字段：`group,index,image_url,source_url,layer,subtype,normalized_value,precision,uncertainty,evidence_level,evidence_text,location,rights_status,notes`。

预测字段增加：`extractor_version,raw_match,matched_text,predicted_layer,predicted_value,confidence,errors`，禁止回写gold。

必测反例：

- 中文证据夹英文 `Summer 1972`：只识别前言日期，且摄影日期留空。
- “no individual capture date / 单张拍摄年未标”：否定作用域测试。
- 日文caption无日期、中文证据有 `1995/07/01`：跨语言字段测试。
- 英文署名题注：作者、作品名、地点、年份连写。
- Shabazz多年份/多城市逐图绑定。
- Holland单图1975/1976与URL系列标签1970s分层。
- URL路径年份误抽：`2023/02`、`2016/06` 一律不得成为年代值。
- 相对时间、季节伪造月日、未知项误填、层级串用、授权过度断言均列严重错误。

指标按层统计 precision/recall/F1、作用域准确率、精度准确率、URL误抽率、未知误填率；另计严重错误数。
