# The Anthropic Java SDK maps JSON with Jackson (reflection + Kotlin metadata): keep its model
# classes and Jackson's annotations, or requests/responses would be (de)serialised as empty.
-keep class com.anthropic.** { *; }
-keep class com.fasterxml.jackson.** { *; }
-keepattributes Signature,InnerClasses,EnclosingMethod,*Annotation*,RuntimeVisibleAnnotations,RuntimeVisibleParameterAnnotations,KotlinMetadata
-keep class kotlin.Metadata { *; }
-keep class kotlin.reflect.** { *; }
-keepclassmembers class * { @com.fasterxml.jackson.annotation.* *; }

# Optional/JVM-only pieces the SDK references but Android never loads.
-dontwarn com.fasterxml.jackson.databind.ext.**
-dontwarn com.github.victools.**
-dontwarn io.swagger.**
-dontwarn com.google.errorprone.annotations.**
-dontwarn javax.annotation.**
-dontwarn java.beans.**
-dontwarn org.slf4j.**
-dontwarn okhttp3.internal.platform.**
-dontwarn org.conscrypt.**
-dontwarn org.bouncycastle.**
-dontwarn org.openjsse.**
-dontwarn java.lang.reflect.AnnotatedType
