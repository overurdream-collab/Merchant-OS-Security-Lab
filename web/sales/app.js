const products=[
{id:1,name:"حقيبة يومية أنيقة",merchant:"متجر لمسة",category:"أزياء",price:18500,icon:"◈",badge:"مختار لك"},
{id:2,name:"طقم عناية يومي",merchant:"بيت الجمال",category:"عناية",price:12500,icon:"✦",badge:"الأكثر مشاهدة"},
{id:3,name:"منظم منزلي عملي",merchant:"دارك",category:"منزل",price:9800,icon:"▦",badge:"عرض اليوم"},
{id:4,name:"سماعة لاسلكية",merchant:"تك ستور",category:"إلكترونيات",price:32000,icon:"◉",badge:"رائج"},
{id:5,name:"طقم أطفال مريح",merchant:"عالم الصغار",category:"أطفال",price:15000,icon:"◇",badge:"جديد"},
{id:6,name:"عباءة بتصميم هادئ",merchant:"أناقة",category:"أزياء",price:27000,icon:"◐",badge:"مختار لك"},
{id:7,name:"مجموعة تنظيم المطبخ",merchant:"بيتك",category:"منزل",price:11200,icon:"⌂",badge:"عرض اليوم"},
{id:8,name:"ساعة ذكية",merchant:"تك ستور",category:"إلكترونيات",price:45500,icon:"◍",badge:"رائج"}];
const grid=document.querySelector("#productGrid"),count=document.querySelector("#cartCount");let cart=0;
function render(list){grid.innerHTML=list.map(p=>`<article class="product"><div class="product-visual"><span class="badge">${p.badge}</span><span>${p.icon}</span></div><div class="product-body"><span class="merchant">${p.merchant} · ${p.category}</span><h3>${p.name}</h3><div class="meta"><span class="price">${p.price.toLocaleString("ar-YE")} <small>ريال</small></span><button class="add" data-id="${p.id}">اطلب الآن</button></div></div></article>`).join("");document.querySelectorAll(".add").forEach(b=>b.onclick=()=>{cart++;count.textContent=cart;b.textContent="تمت الإضافة ✓";setTimeout(()=>b.textContent="اطلب الآن",900)})}
render(products);
document.querySelectorAll(".chip").forEach(c=>c.onclick=()=>{document.querySelectorAll(".chip").forEach(x=>x.classList.remove("active"));c.classList.add("active");const cat=c.dataset.category;render(cat==="all"?products:products.filter(p=>p.category===cat))});
document.querySelector("#searchForm").onsubmit=e=>{e.preventDefault();const q=document.querySelector("#searchInput").value.trim().toLowerCase();render(q?products.filter(p=>(p.name+" "+p.merchant+" "+p.category).toLowerCase().includes(q)):products)};
document.querySelector("#cartButton").onclick=()=>document.querySelector("#for-you").scrollIntoView({behavior:"smooth"});
