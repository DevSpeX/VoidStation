// SPDX-License-Identifier: GPL-3.0-or-later
// Hintergrund: zwei weiche Lichtflecken wie im Web, optional Hintergrundbild
import QtQuick
import QtQuick.Shapes

Item {
    id: bg
    property string wallpaper: ""
    Rectangle { anchors.fill: parent; color: Ui.c.bgMain }
    Shape {
        anchors.fill: parent
        visible: !bg.wallpaper
        preferredRendererType: Shape.CurveRenderer
        ShapePath {
            strokeWidth: -1
            fillGradient: RadialGradient {
                centerX: bg.width * 0.15; centerY: 0; focalX: centerX; focalY: centerY
                centerRadius: Math.max(bg.width * 1.2, bg.height * 0.9) * 0.6
                GradientStop { position: 0; color: Ui.c.bgRadial1 }
                GradientStop { position: 1; color: Ui.alpha(Ui.c.bgRadial1, 0) }
            }
            PathRectangle { x: 0; y: 0; width: bg.width; height: bg.height }
        }
        ShapePath {
            strokeWidth: -1
            fillGradient: RadialGradient {
                centerX: bg.width; centerY: bg.height; focalX: centerX; focalY: centerY
                centerRadius: Math.max(bg.width * 0.9, bg.height * 0.8) * 0.55
                GradientStop { position: 0; color: Ui.c.bgRadial2 }
                GradientStop { position: 1; color: Ui.alpha(Ui.c.bgRadial2, 0) }
            }
            PathRectangle { x: 0; y: 0; width: bg.width; height: bg.height }
        }
    }
    Image {
        anchors.fill: parent
        visible: !!bg.wallpaper
        source: bg.wallpaper
        fillMode: Image.PreserveAspectCrop
        asynchronous: true
    }
    Rectangle {
        anchors.fill: parent
        visible: !!bg.wallpaper
        gradient: Gradient {
            GradientStop { position: 0; color: "#8c0a0b0d" }
            GradientStop { position: 1; color: "#d90a0b0d" }
        }
    }
}
