// Lit un fichier STEP, le découpe en triangles et écrit un maillage compact pour l'aperçu.
// Usage : step_mesh.exe <entrée.step> <sortie.mesh>
// Sortie : "DCMESH3\0", uint32 sommets, uint32 triangles, float32[sommets*3], uint32[triangles*3],
//          uint8[sommets*4] couleur sRGB et opacité de chaque sommet (celles de sa face dans le fichier, sinon le bleu
//          par défaut, opaque). L'opacité vient du fichier ; à défaut, une matière nommée comme un vitrage
//          (Fusion écrit « Polycarbonate », « Glass »... dans le nom de la couleur) est rendue translucide.
// Codes de sortie : 0 réussi, 1 arguments, 2 lecture STEP, 3 aucune surface, 4 limite, 5 écriture, 6 exception.
#define NOMINMAX
#define WIN32_LEAN_AND_MEAN
#include <windows.h>
#include <cstdio>
#include <cstdint>
#include <algorithm>
#include <exception>
#include <string>
#include <vector>
#include <STEPCAFControl_Reader.hxx>
#include <TDocStd_Document.hxx>
#include <NCollection_Sequence.hxx>
#include <XCAFDoc_DocumentTool.hxx>
#include <XCAFDoc_ShapeTool.hxx>
#include <XCAFPrs.hxx>
#include <XCAFPrs_Style.hxx>
#include <StepData_StepModel.hxx>
#include <StepVisual_ColourRgb.hxx>
#include <TCollection_HAsciiString.hxx>
#include <Quantity_ColorRGBA.hxx>
#include <cctype>
#include <Quantity_Color.hxx>
#include <NCollection_DataMap.hxx>
#include <NCollection_IndexedDataMap.hxx>
#include <TopTools_ShapeMapHasher.hxx>
#include <TopoDS_Compound.hxx>
#include <BRep_Builder.hxx>
#include <IFSelect_ReturnStatus.hxx>
#include <BRepMesh_IncrementalMesh.hxx>
#include <BRepBndLib.hxx>
#include <Bnd_Box.hxx>
#include <BRep_Tool.hxx>
#include <Poly_Triangulation.hxx>
#include <TopExp_Explorer.hxx>
#include <TopLoc_Location.hxx>
#include <TopoDS.hxx>
#include <TopoDS_Face.hxx>
#include <Standard_Failure.hxx>

static const uint32_t MAX_VERTICES = 20000000, MAX_FACES = 30000000;
static const uint32_t DEFAULT_COLOR =
    65 | 135 << 8 | 205 << 16 | 255u << 24; // bleu de l'aperçu, octets R, V, B, opacité
static const uint32_t GLAZING_ALPHA = 80;   // opacité donnée à un vitrage reconnu à son nom
static const char *const GLAZING_WORDS[] = {"polycarbonate", "acrylic", "glass", "transparent", "translucent",
                                            "plexi",         "pmma",    "clear", "tinted"};

static uint32_t byte(double v) {
    return uint32_t((std::min)(255.0, (std::max)(0.0, v * 255.0 + 0.5)));
}

static bool is_glazing(std::string name) {
    for (char &c : name)
        c = char(std::tolower(static_cast<unsigned char>(c)));
    for (const char *word : GLAZING_WORDS)
        if (name.find(word) != std::string::npos) return true;
    return false;
}

static std::string utf8(const wchar_t *text) {
    int n = WideCharToMultiByte(CP_UTF8, 0, text, -1, nullptr, 0, nullptr, nullptr);
    std::string out(n > 0 ? n - 1 : 0, '\0');
    if (n > 1) WideCharToMultiByte(CP_UTF8, 0, text, -1, out.data(), n, nullptr, nullptr);
    return out;
}

static int write_mesh(const wchar_t *path, const std::vector<float> &points, const std::vector<uint32_t> &faces,
                      const std::vector<uint32_t> &colors) {
    std::wstring part = std::wstring(path) + L".part";
    FILE *f = nullptr;
    if (_wfopen_s(&f, part.c_str(), L"wb") || !f) return 5;
    uint32_t header[2] = {uint32_t(points.size() / 3), uint32_t(faces.size() / 3)};
    bool ok = fwrite("DCMESH3", 1, 8, f) == 8 && fwrite(header, 4, 2, f) == 2 &&
              fwrite(points.data(), 4, points.size(), f) == points.size() &&
              fwrite(faces.data(), 4, faces.size(), f) == faces.size() &&
              fwrite(colors.data(), 4, colors.size(), f) == colors.size();
    ok = fclose(f) == 0 && ok;
    if (!ok || !MoveFileExW(part.c_str(), path, MOVEFILE_REPLACE_EXISTING)) {
        DeleteFileW(part.c_str());
        return 5;
    }
    return 0;
}

static int run(const wchar_t *input, const wchar_t *output) {
    TopoDS_Compound shape;
    NCollection_DataMap<TopoDS_Shape, uint32_t, TopTools_ShapeMapHasher> face_colors;
    std::vector<uint32_t> glazing;
    {
        // Le lecteur garde tout le graphe STEP en mémoire : il est libéré, avec le document, avant le maillage.
        Handle(TDocStd_Document) document = new TDocStd_Document("BinXCAF");
        {
            STEPCAFControl_Reader reader;
            reader.SetColorMode(true);
            reader.SetNameMode(false);
            reader.SetLayerMode(false);
            reader.SetPropsMode(false);
            reader.SetMetaMode(false);
            reader.SetSHUOMode(false);
            reader.SetGDTMode(false);
            reader.SetMatMode(false);
            if (reader.ReadFile(utf8(input).c_str()) != IFSelect_RetDone) return 2;
            // Couleurs dont le nom désigne un vitrage : le fichier n'en dit pas plus sur leur transparence.
            Handle(StepData_StepModel) model = reader.Reader().StepModel();
            for (int i = 1; !model.IsNull() && i <= model->NbEntities(); ++i) {
                Handle(StepVisual_ColourRgb) colour = Handle(StepVisual_ColourRgb)::DownCast(model->Value(i));
                if (colour.IsNull() || colour->Name().IsNull() || !is_glazing(colour->Name()->ToCString())) continue;
                glazing.push_back(byte(colour->Red()) | byte(colour->Green()) << 8 | byte(colour->Blue()) << 16);
            }
            if (!reader.Transfer(document)) return 3;
        }
        Handle(XCAFDoc_ShapeTool) tool = XCAFDoc_DocumentTool::ShapeTool(document->Main());
        NCollection_Sequence<TDF_Label> roots;
        tool->GetFreeShapes(roots);
        BRep_Builder builder;
        builder.MakeCompound(shape);
        NCollection_IndexedDataMap<TopoDS_Shape, XCAFPrs_Style, TopTools_ShapeMapHasher> styles;
        for (int i = 1; i <= roots.Length(); ++i) {
            TopoDS_Shape root = tool->GetShape(roots.Value(i));
            if (root.IsNull()) continue;
            builder.Add(shape, root);
            XCAFPrs::CollectStyleSettings(roots.Value(i), TopLoc_Location(), styles);
        }
        // Du plus englobant au plus précis : la couleur d'une face l'emporte sur celle de son solide.
        for (int kind = TopAbs_COMPOUND; kind <= TopAbs_FACE; ++kind) {
            for (int i = 1; i <= styles.Extent(); ++i) {
                const TopoDS_Shape &styled = styles.FindKey(i);
                const XCAFPrs_Style &style = styles.FindFromIndex(i);
                if (styled.ShapeType() != kind || !style.IsSetColorSurf()) continue;
                double r, g, b;
                style.GetColorSurf().Values(r, g, b, Quantity_TOC_sRGB);
                const uint32_t rgb = byte(r) | byte(g) << 8 | byte(b) << 16;
                uint32_t alpha = byte(style.GetColorSurfRGBA().Alpha());
                if (alpha == 255 && std::find(glazing.begin(), glazing.end(), rgb) != glazing.end())
                    alpha = GLAZING_ALPHA;
                const uint32_t color = rgb | alpha << 24;
                for (TopExp_Explorer it(styled, TopAbs_FACE); it.More(); it.Next())
                    face_colors.Bind(it.Current(), color);
            }
        }
    }
    if (shape.IsNull()) return 3;
    Bnd_Box box;
    BRepBndLib::Add(shape, box);
    if (box.IsVoid()) return 3;
    double x0, y0, z0, x1, y1, z1;
    box.Get(x0, y0, z0, x1, y1, z1);
    double size = (std::max)({x1 - x0, y1 - y0, z1 - z0});
    if (!(size > 0)) return 3;
    // Flèche de 0,1 % de la plus grande dimension, angle 0,5 rad, en parallèle.
    BRepMesh_IncrementalMesh mesher(shape, size * 0.001, false, 0.5, true);
    std::vector<float> points;
    std::vector<uint32_t> faces;
    std::vector<uint32_t> colors;
    for (TopExp_Explorer it(shape, TopAbs_FACE); it.More(); it.Next()) {
        const TopoDS_Face &face = TopoDS::Face(it.Current());
        TopLoc_Location location;
        Handle(Poly_Triangulation) tri = BRep_Tool::Triangulation(face, location);
        if (tri.IsNull()) continue;
        const gp_Trsf transform = location.Transformation();
        const size_t base = points.size() / 3;
        const int nodes = tri->NbNodes(), triangles = tri->NbTriangles();
        if (base + nodes > MAX_VERTICES || faces.size() / 3 + triangles > MAX_FACES) return 4;
        for (int i = 1; i <= nodes; ++i) {
            gp_Pnt p = tri->Node(i).Transformed(transform);
            points.push_back(float(p.X()));
            points.push_back(float(p.Y()));
            points.push_back(float(p.Z()));
        }
        uint32_t color = DEFAULT_COLOR;
        face_colors.Find(face, color);
        colors.insert(colors.end(), nodes, color);
        const bool reversed = face.Orientation() == TopAbs_REVERSED;
        for (int i = 1; i <= triangles; ++i) {
            int a, b, c;
            tri->Triangle(i).Get(a, b, c);
            if (a < 1 || b < 1 || c < 1 || a > nodes || b > nodes || c > nodes) return 6;
            faces.push_back(uint32_t(base + a - 1));
            faces.push_back(uint32_t(base + (reversed ? c : b) - 1));
            faces.push_back(uint32_t(base + (reversed ? b : c) - 1));
        }
    }
    if (faces.empty()) return 3;
    return write_mesh(output, points, faces, colors);
}

int wmain(int argc, wchar_t **argv) {
    SetErrorMode(SEM_FAILCRITICALERRORS | SEM_NOGPFAULTERRORBOX | SEM_NOOPENFILEERRORBOX);
    if (argc != 3) {
        fwprintf(stderr, L"usage: step_mesh <input.step> <output.mesh>\n");
        return 1;
    }
    try {
        return run(argv[1], argv[2]);
    } catch (const Standard_Failure &failure) {
        fprintf(stderr, "OCCT: %s\n", failure.what());
    } catch (const std::exception &failure) {
        fprintf(stderr, "%s\n", failure.what());
    } catch (...) {
        fprintf(stderr, "unknown failure\n");
    }
    return 6;
}
