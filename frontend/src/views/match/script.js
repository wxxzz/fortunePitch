document.addEventListener('DOMContentLoaded', function() {
    
    // 获取所有的 Tab 按钮和内容面板
    const tabBtns = document.querySelectorAll('.tab-btn');
    const tabPanes = document.querySelectorAll('.tab-pane');

    // 为每个按钮添加点击事件
    tabBtns.forEach(btn => {
        btn.addEventListener('click', () => {
            // 1. 移除所有按钮的 active 类
            tabBtns.forEach(b => b.classList.remove('active'));
            // 2. 隐藏所有内容面板
            tabPanes.forEach(p => p.classList.remove('active'));

            // 3. 给当前点击的按钮添加 active
            btn.classList.add('active');

            // 4. 显示对应的面板 (通过 data-target 属性匹配 ID)
            const targetId = btn.getAttribute('data-target');
            const targetPane = document.getElementById(targetId);
            
            if (targetPane) {
                targetPane.classList.add('active');
            }
        });
    });

    // 可选：点击赔率格子的交互反馈
    const oddsItems = document.querySelectorAll('.odds-item');
    oddsItems.forEach(item => {
        item.addEventListener('click', function() {
            // 简单的选中效果：切换背景色
            if(this.style.backgroundColor === 'rgb(40, 167, 69)') { // 绿色
                this.style.backgroundColor = '';
                this.style