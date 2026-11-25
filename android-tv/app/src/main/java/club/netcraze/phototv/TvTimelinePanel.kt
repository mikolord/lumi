package club.netcraze.phototv

import android.app.Activity
import android.graphics.Canvas
import android.graphics.Color
import android.graphics.Paint
import android.graphics.Typeface
import android.graphics.drawable.GradientDrawable
import android.view.Gravity
import android.view.KeyEvent
import android.view.View
import android.widget.FrameLayout
import android.widget.LinearLayout
import android.widget.TextView
import java.time.format.DateTimeFormatter
import java.util.Locale

/** A focus-only date picker: no scrolling/thumbnail work until OK is pressed. */
class TvTimelinePanel(private val activity: Activity, parent: FrameLayout,
                      private val jump: (Int) -> Unit, private val restore: () -> Unit) {
    private fun dp(value:Int)=(value*activity.resources.displayMetrics.density).toInt()
    private val panel=LinearLayout(activity).apply {
        orientation=LinearLayout.VERTICAL;setPadding(dp(22),dp(22),dp(22),dp(22))
        background=GradientDrawable().apply{setColor(0xf51b1d22.toInt());cornerRadius=dp(22).toFloat();setStroke(dp(1),0x556fa9ff)}
        isFocusable=true;isFocusableInTouchMode=true;visibility=View.GONE;elevation=dp(12).toFloat()
        importantForAccessibility=View.IMPORTANT_FOR_ACCESSIBILITY_YES
    }
    private fun label(size:Float,color:Int)=TextView(activity).apply{textSize=size;setTextColor(color);isFocusable=false}
    private val date=label(24f,Color.WHITE).apply{setTypeface(null,Typeface.BOLD)}
    private val detail=label(15f,0xffb4bfce.toInt())
    private val rail=Rail(activity)
    private var index=TvTimelineIndex(emptyList(),IntArray(0))
    private var selected=0
    private var generation=0
    val isOpen get()=panel.visibility==View.VISIBLE
    init {
        panel.addView(label(18f,0xff8ebaff.toInt()).apply{text="По датам"},LinearLayout.LayoutParams(-1,-2))
        panel.addView(date,LinearLayout.LayoutParams(-1,-2).apply{topMargin=dp(14)})
        panel.addView(detail,LinearLayout.LayoutParams(-1,-2).apply{topMargin=dp(6)})
        panel.addView(rail,LinearLayout.LayoutParams(-1,0,1f).apply{topMargin=dp(14);bottomMargin=dp(14)})
        panel.addView(label(13f,0xffb4bfce.toInt()).apply{text="▲ ▼ — выбрать дату\nУдерживай — быстрее\nOK — перейти · Назад — закрыть"},LinearLayout.LayoutParams(-1,-2))
        parent.addView(panel,FrameLayout.LayoutParams(dp(300),-1,Gravity.END).apply{setMargins(dp(12),dp(12),dp(16),dp(20))})
        panel.setOnKeyListener { _,code,event ->
            if(!isOpen)return@setOnKeyListener false
            if(event.action==KeyEvent.ACTION_UP)return@setOnKeyListener code in handled
            if(event.action!=KeyEvent.ACTION_DOWN)return@setOnKeyListener false
            if(code==KeyEvent.KEYCODE_BACK||code==KeyEvent.KEYCODE_DPAD_LEFT){dismiss(true);return@setOnKeyListener true}
            if(index.stops.isEmpty())return@setOnKeyListener code in handled
            when(code){
                KeyEvent.KEYCODE_DPAD_UP,KeyEvent.KEYCODE_DPAD_DOWN -> {val direction=if(code==KeyEvent.KEYCODE_DPAD_UP)-1 else 1;val step=when{event.repeatCount>=20->14;event.repeatCount>=8->4;else->1};selected=(selected+direction*step).coerceIn(index.stops.indices);paint()}
                KeyEvent.KEYCODE_PAGE_UP,KeyEvent.KEYCODE_CHANNEL_UP -> {selected=index.nextMonth(selected,-1);paint()}
                KeyEvent.KEYCODE_PAGE_DOWN,KeyEvent.KEYCODE_CHANNEL_DOWN -> {selected=index.nextMonth(selected,1);paint()}
                KeyEvent.KEYCODE_DPAD_CENTER,KeyEvent.KEYCODE_ENTER,KeyEvent.KEYCODE_NUMPAD_ENTER -> if(event.repeatCount==0){val position=index.stops[selected].firstPosition;dismiss(false);jump(position)}
                KeyEvent.KEYCODE_DPAD_RIGHT -> Unit
                else -> return@setOnKeyListener false
            }
            true
        }
    }
    fun show(items:List<MediaItem>,position:Int){
        val token=++generation;index=TvTimelineIndex(emptyList(),IntArray(0));date.text="Готовим даты…";detail.text="";rail.ratio=0f
        panel.animate().cancel();panel.visibility=View.VISIBLE;panel.alpha=0f;panel.translationX=dp(20).toFloat();panel.animate().alpha(1f).translationX(0f).setDuration(180).start();panel.requestFocus()
        Thread{
            val result=TvTimelineIndex.build(items)
            activity.runOnUiThread{if(generation!=token||!isOpen||activity.isDestroyed)return@runOnUiThread;index=result;selected=index.stopAt(position);paint()}
        }.start()
    }
    private fun paint(){
        val stop=index.stops.getOrNull(selected)?:return
        date.text=stop.day?.format(DateTimeFormatter.ofPattern("d MMMM yyyy",Locale.forLanguageTag("ru")))?:"Без даты"
        detail.text="${stop.count} объектов · ${selected+1} из ${index.stops.size} дат"
        rail.ratio=if(index.stops.size<=1)0f else selected.toFloat()/index.stops.lastIndex
        panel.contentDescription="${date.text}, ${detail.text}"
    }
    fun dismiss(returnFocus:Boolean){
        generation++;if(!isOpen)return
        panel.animate().cancel();panel.visibility=View.GONE;index=TvTimelineIndex(emptyList(),IntArray(0))
        if(returnFocus)restore()
    }
    companion object {
        private val handled=setOf(KeyEvent.KEYCODE_BACK,KeyEvent.KEYCODE_DPAD_LEFT,KeyEvent.KEYCODE_DPAD_RIGHT,KeyEvent.KEYCODE_DPAD_UP,KeyEvent.KEYCODE_DPAD_DOWN,KeyEvent.KEYCODE_DPAD_CENTER,KeyEvent.KEYCODE_ENTER,KeyEvent.KEYCODE_NUMPAD_ENTER,KeyEvent.KEYCODE_PAGE_UP,KeyEvent.KEYCODE_PAGE_DOWN,KeyEvent.KEYCODE_CHANNEL_UP,KeyEvent.KEYCODE_CHANNEL_DOWN)
    }
    private class Rail(activity:Activity):View(activity){
        private val ink=Paint(Paint.ANTI_ALIAS_FLAG).apply{strokeCap=Paint.Cap.ROUND}
        var ratio=0f;set(value){field=value;invalidate()}
        override fun onDraw(canvas:Canvas){super.onDraw(canvas);val density=resources.displayMetrics.density;val x=width-8*density;val inset=5*density;val range=(height-2*inset).coerceAtLeast(1f)
            for(n in 0..32){val fraction=n/32f;val strength=(1f-kotlin.math.abs(fraction-ratio)*6f).coerceAtLeast(0f);ink.color=Color.WHITE;ink.alpha=(45+150*strength).toInt();ink.strokeWidth=2*density;val y=inset+fraction*range;canvas.drawLine(x-(8+20*strength)*density,y,x,y,ink)}
            ink.color=0xff8ebaff.toInt();ink.alpha=255;ink.strokeWidth=4*density;val y=inset+ratio*range;canvas.drawLine(x-36*density,y,x,y,ink)
        }
    }
}
