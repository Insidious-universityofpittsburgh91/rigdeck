// Headless map exporter for Rig Deck.
//
// TsMap ships as a WinForms app: you point it at the game, click around, and it draws.
// Rig Deck needs the same data without a window and in a form a tablet can draw at any
// zoom, so this walks the parsed map and writes the road network out as vector cells.
//
//   MapExport.exe --game "<game dir>" --out "<dir>" [--mod <file>]... [--cell 4096]
//                 [--map <name>] [--png <file> [--png-size 4096]]
//   MapExport.exe --game "<game dir>" [--mod <file>]... --list-maps
//
// Mods are passed in load order, highest priority first -- the same order the game logs
// when it mounts them.
//
// --list-maps prints the names of the maps this game and its mods provide, one per
// line, and exits. Nothing is parsed, so it answers quickly enough for a menu.
//
// --map picks a single .mbd by name ("europe", "hungary", ...). Standalone map mods add
// their own .mbd and can sit on the same coordinates as the base map, so without this
// they come out drawn on top of each other. The names found are printed on every run.

using System;
using System.Collections.Generic;
using System.Drawing;
using System.Globalization;
using System.IO;
using System.Linq;
using System.Text;
using TsMap;
using TsMap.TsItem;

namespace MapExport
{
    internal static class Program
    {
        private const int RoadSteps = 8;

        private static int Main(string[] args)
        {
            CultureInfo.DefaultThreadCurrentCulture = CultureInfo.InvariantCulture;
            System.Threading.Thread.CurrentThread.CurrentCulture = CultureInfo.InvariantCulture;

            string gameDir = null, outDir = null, pngPath = null, mapName = null;
            var mods = new List<string>();
            var cellSize = 4096f;
            var pngSize = 4096;
            var listMaps = false;

            for (var i = 0; i < args.Length; i++)
            {
                switch (args[i])
                {
                    case "--game": gameDir = args[++i]; break;
                    case "--out": outDir = args[++i]; break;
                    case "--mod": mods.Add(args[++i]); break;
                    case "--cell": cellSize = float.Parse(args[++i], CultureInfo.InvariantCulture); break;
                    case "--map": mapName = args[++i]; break;
                    case "--list-maps": listMaps = true; break;
                    case "--png": pngPath = args[++i]; break;
                    case "--png-size": pngSize = int.Parse(args[++i], CultureInfo.InvariantCulture); break;
                    default:
                        Console.Error.WriteLine($"unknown argument: {args[i]}");
                        return 2;
                }
            }

            if (gameDir == null || (outDir == null && !listMaps))
            {
                Console.Error.WriteLine("usage: MapExport --game <dir> --out <dir> [--mod <file>]...");
                return 2;
            }
            if (!Directory.Exists(gameDir))
            {
                Console.Error.WriteLine($"game directory not found: {gameDir}");
                return 2;
            }

            foreach (var mod in mods)
            {
                if (File.Exists(mod)) continue;
                Console.Error.WriteLine($"mod file not found: {mod}");
                return 2;
            }

            if (listMaps)
            {
                var lister = new TsMapper(gameDir, mods.Select(m => new Mod(m) { Load = true }).ToList());
                foreach (var name in lister.ListMaps()) Console.WriteLine(name);
                return 0;
            }

            Console.WriteLine($"  game : {gameDir}");
            foreach (var mod in mods) Console.WriteLine($"  mod  : {Path.GetFileName(mod)}");

            if (mapName != null) Console.WriteLine($"  map  : {mapName}");

            var modList = mods.Select(m => new Mod(m) { Load = true }).ToList();
            var mapper = new TsMapper(gameDir, modList) { MapName = mapName };

            Console.Write("  parsing... ");
            var started = DateTime.UtcNow;
            mapper.Parse();
            Console.WriteLine($"{(DateTime.UtcNow - started).TotalSeconds:F1}s  " +
                              $"({mapper.Roads.Count} roads, {mapper.Prefabs.Count} prefabs, {mapper.Cities.Count} cities)");

            if (mapper.Roads.Count == 0 && mapper.Prefabs.Count == 0)
            {
                Console.Error.WriteLine("  nothing was parsed -- the game files could not be read");
                return 1;
            }

            var guards = new HashSet<byte>(mapper.GetDlcGuardsForCurrentGame().Where(g => g.Enabled).Select(g => g.Index));
            var cells = new Dictionary<string, Cell>();

            Cell CellAt(int cx, int cz)
            {
                var key = cx + "_" + cz;
                if (!cells.TryGetValue(key, out var cell)) cells[key] = cell = new Cell();
                return cell;
            }

            void Place(List<PointF> pts, Action<Cell> add)
            {
                if (pts.Count < 2) return;
                float minX = pts[0].X, maxX = pts[0].X, minZ = pts[0].Y, maxZ = pts[0].Y;
                foreach (var p in pts)
                {
                    if (p.X < minX) minX = p.X;
                    if (p.X > maxX) maxX = p.X;
                    if (p.Y < minZ) minZ = p.Y;
                    if (p.Y > maxZ) maxZ = p.Y;
                }
                for (var cx = (int)Math.Floor(minX / cellSize); cx <= (int)Math.Floor(maxX / cellSize); cx++)
                for (var cz = (int)Math.Floor(minZ / cellSize); cz <= (int)Math.Floor(maxZ / cellSize); cz++)
                    add(CellAt(cx, cz));
            }

            // Roads. TsMap computes these lazily while drawing; the Hermite fit below is the
            // same one its renderer uses, so the shapes match what the map window shows.
            var roadCount = 0;
            foreach (var road in mapper.Roads)
            {
                if (!guards.Contains(road.DlcGuard) || road.Hidden) continue;
                var start = road.GetStartNode();
                var end = road.GetEndNode();
                if (start == null || end == null) continue;

                var pts = new List<PointF>(RoadSteps);
                var radius = Math.Sqrt(Math.Pow(start.X - end.X, 2) + Math.Pow(start.Z - end.Z, 2));
                var tanSx = Math.Cos(-(Math.PI * 0.5f - start.Rotation)) * radius;
                var tanEx = Math.Cos(-(Math.PI * 0.5f - end.Rotation)) * radius;
                var tanSz = Math.Sin(-(Math.PI * 0.5f - start.Rotation)) * radius;
                var tanEz = Math.Sin(-(Math.PI * 0.5f - end.Rotation)) * radius;
                for (var i = 0; i < RoadSteps; i++)
                {
                    var s = i / (float)(RoadSteps - 1);
                    pts.Add(new PointF((float)TsRoadLook.Hermite(s, start.X, end.X, tanSx, tanEx),
                                       (float)TsRoadLook.Hermite(s, start.Z, end.Z, tanSz, tanEz)));
                }

                var width = road.RoadLook?.GetWidth() ?? 8f;
                var line = Encode(pts, width, road.IsSecret);
                Place(pts, c => c.Roads.Add(line));
                roadCount++;
            }

            // Prefabs: junctions, service areas and company yards. Their road links keep the
            // network connected -- without them every interchange reads as a gap.
            int linkCount = 0, areaCount = 0;
            foreach (var prefab in mapper.Prefabs)
            {
                if (!guards.Contains(prefab.DlcGuard) || prefab.Prefab?.PrefabNodes == null) continue;
                if (prefab.Nodes == null || prefab.Nodes.Count == 0) continue;

                var origin = mapper.GetNodeByUid(prefab.Nodes[0]);
                if (origin == null) continue;
                if (prefab.Origin >= prefab.Prefab.PrefabNodes.Count) continue;

                var originPoint = prefab.Prefab.PrefabNodes[prefab.Origin];
                var rot = (float)(origin.Rotation - Math.PI -
                                  Math.Atan2(originPoint.RotZ, originPoint.RotX) + Math.PI / 2);
                var baseX = origin.X - originPoint.X;
                var baseZ = origin.Z - originPoint.Z;

                PointF World(TsMapPoint p) =>
                    RenderHelper.RotatePoint(baseX + p.X, baseZ + p.Z, rot, origin.X, origin.Z);

                var points = prefab.Prefab.MapPoints;
                var walked = new List<int>();
                for (var i = 0; i < points.Count; i++)
                {
                    var point = points[i];
                    walked.Add(i);

                    if (point.LaneCount == -1) // an area outline, not a road
                    {
                        var poly = new Dictionary<int, PointF>();
                        var next = i;
                        do
                        {
                            if (points[next].Neighbours.Count == 0) break;
                            foreach (var neighbour in points[next].Neighbours)
                            {
                                if (!poly.ContainsKey(neighbour))
                                {
                                    next = neighbour;
                                    poly.Add(next, World(points[next]));
                                    break;
                                }
                                next = -1;
                            }
                        } while (next != -1);

                        if (poly.Count < 3) continue;
                        var ring = poly.Values.ToList();
                        Place(ring, c => c.Areas.Add(Encode(ring)));
                        areaCount++;
                        continue;
                    }

                    foreach (var neighbourIndex in point.Neighbours)
                    {
                        if (walked.Contains(neighbourIndex)) continue;
                        var neighbour = points[neighbourIndex];
                        if ((point.Hidden || neighbour.Hidden) &&
                            prefab.Prefab.PrefabNodes.Count + 1 < points.Count) continue;

                        var lanes = LaneCount(prefab, point, i);
                        var otherLanes = LaneCount(prefab, neighbour, neighbourIndex);
                        var width = 4.5f * Math.Max(1, Math.Max(lanes, otherLanes));

                        var link = new List<PointF> { World(point), World(neighbour) };
                        var encoded = Encode(link, width, false);
                        Place(link, c => c.Roads.Add(encoded));
                        linkCount++;
                    }
                }
            }

            // Ferry and train lines, drawn as the dashed hops they are in game.
            var ferryCount = 0;
            var seenFerries = new HashSet<string>();
            foreach (var ferry in mapper.FerryConnections)
            {
                foreach (var conn in mapper.LookupFerryConnection(ferry.FerryPortId))
                {
                    var key = Math.Min(conn.StartPortToken, conn.EndPortToken) + "-" +
                              Math.Max(conn.StartPortToken, conn.EndPortToken);
                    if (!seenFerries.Add(key)) continue;

                    var line = new List<PointF> { conn.StartPortLocation };
                    line.AddRange(conn.Connections.Select(p => new PointF(p.X, p.Z)));
                    line.Add(conn.EndPortLocation);
                    var encoded = Encode(line);
                    Place(line, c => c.Ferries.Add(encoded));
                    ferryCount++;
                }
            }

            // City labels, in the game's own language where a localisation exists.
            var cityCount = 0;
            var namedGroups = new HashSet<string>();
            foreach (var city in mapper.Cities)
            {
                if (city.Hidden || city.City == null) continue;
                if (city.City.Group != null && !namedGroups.Add(city.City.Group)) continue;

                var node = mapper.GetNodeByUid(city.NodeUid);
                var x = node?.X ?? city.X;
                var z = node?.Z ?? city.Z;
                var name = mapper.Localization?.GetLocaleValue(city.City.LocalizationToken) ?? city.City.Name;
                if (string.IsNullOrEmpty(name)) continue;

                var entry = "[" + N(x) + "," + N(z) + "," + Quote(name) + "]";
                CellAt((int)Math.Floor(x / cellSize), (int)Math.Floor(z / cellSize)).Cities.Add(entry);
                cityCount++;
            }

            // Places worth stopping at: fuel, service, parking, garages, dealers and the
            // company yards themselves. These are the game's own map overlays, so whatever
            // it puts on its world map ends up on the tablet -- including a mod's.
            //
            // TsMap keeps its overlay list internal and offers exactly one way out of the
            // assembly, ExportOverlays, so the list is written to a scratch file and read
            // straight back. Round-tripping a few thousand rows through JSON costs nothing
            // next to parsing the map, and it means ts-map stays an untouched clone.
            var poiCount = 0;
            var poiKinds = new SortedDictionary<string, int>();
            var unknown = new SortedDictionary<string, int>();
            var scratch = Path.Combine(Path.GetTempPath(), "rigdeck-overlays-" + Guid.NewGuid().ToString("N"));
            try
            {
                Directory.CreateDirectory(scratch);
                mapper.ExportOverlays(ExportFlags.OverlayList, scratch);
                var overlaysFile = Path.Combine(scratch, "Overlays.json");
                if (File.Exists(overlaysFile))
                {
                    var overlays = Newtonsoft.Json.Linq.JArray.Parse(File.ReadAllText(overlaysFile));
                    foreach (var overlay in overlays)
                    {
                        if ((bool?)overlay["IsSecret"] == true) continue;
                        var guard = (byte?)overlay["DlcGuard"] ?? 0;
                        if (!guards.Contains(guard)) continue;

                        var type = (string)overlay["Type"] ?? "";
                        var name = (string)overlay["Name"] ?? "";
                        var kind = Kind(type, name);
                        if (kind == null)
                        {
                            if (type == "Overlay") unknown[name] = unknown.TryGetValue(name, out var seen) ? seen + 1 : 1;
                            continue;
                        }

                        var x = (float?)overlay["X"] ?? 0f;
                        var z = (float?)overlay["Y"] ?? 0f;
                        // Only companies carry a label. Everything else is one icon with one
                        // meaning, and "Fuel" written beside a fuel pump is just noise.
                        var entry = "[" + N(x) + "," + N(z) + "," + Quote(kind) +
                                    (kind == "company" ? "," + Quote(Pretty(name)) : "") + "]";
                        CellAt((int)Math.Floor(x / cellSize), (int)Math.Floor(z / cellSize)).Points.Add(entry);
                        poiKinds[kind] = poiKinds.TryGetValue(kind, out var count) ? count + 1 : 1;
                        poiCount++;
                    }
                }
            }
            catch (Exception exc)
            {
                Console.Error.WriteLine("  overlays could not be read: " + exc.Message);
            }
            finally
            {
                try { Directory.Delete(scratch, true); } catch { /* a temp dir left behind is not worth failing over */ }
            }

            // Write it out. One file per cell, fetched by the tablet only as it drives into
            // range, so the panel never loads a continent to show three kilometres of road.
            var cellDir = Path.Combine(outDir, "cells");
            if (Directory.Exists(cellDir)) Directory.Delete(cellDir, true);
            Directory.CreateDirectory(cellDir);

            long bytes = 0;
            foreach (var pair in cells)
            {
                var json = pair.Value.ToJson();
                var path = Path.Combine(cellDir, pair.Key + ".json");
                File.WriteAllText(path, json, new UTF8Encoding(false));
                bytes += json.Length;
            }

            var meta = new StringBuilder();
            meta.Append("{\n");
            meta.Append("  \"game\": ").Append(Quote(mapper.IsEts2 ? "ETS2" : "ATS")).Append(",\n");
            meta.Append("  \"cellSize\": ").Append(N(cellSize)).Append(",\n");
            meta.Append("  \"bounds\": [").Append(N(mapper.minX)).Append(",").Append(N(mapper.minZ))
                .Append(",").Append(N(mapper.maxX)).Append(",").Append(N(mapper.maxZ)).Append("],\n");
            meta.Append("  \"counts\": {\"roads\": ").Append(roadCount).Append(", \"links\": ").Append(linkCount)
                .Append(", \"areas\": ").Append(areaCount).Append(", \"ferries\": ").Append(ferryCount)
                .Append(", \"cities\": ").Append(cityCount).Append(", \"places\": ").Append(poiCount)
                .Append(", \"cells\": ").Append(cells.Count).Append("},\n");
            meta.Append("  \"mods\": [").Append(string.Join(", ", mods.Select(m => Quote(Path.GetFileName(m))))).Append("],\n");
            // What this export was made from, so the panel can notice later that the game
            // has moved on -- a ProMods update changes a mod's file name, and a map DLC
            // adds an archive here. Without this the map would quietly stay a version
            // behind and the first sign of it would be a road that is not there.
            var dlcs = Directory.GetFiles(gameDir, "dlc_*.scs")
                                .Select(Path.GetFileName).OrderBy(n => n, StringComparer.OrdinalIgnoreCase).ToList();
            meta.Append("  \"gameDir\": ").Append(Quote(gameDir)).Append(",\n");
            meta.Append("  \"dlcs\": [").Append(string.Join(", ", dlcs.Select(Quote))).Append("],\n");
            meta.Append("  \"exported\": ").Append(Quote(DateTime.Now.ToString("yyyy-MM-dd HH:mm"))).Append("\n");
            meta.Append("}\n");
            File.WriteAllText(Path.Combine(outDir, "meta.json"), meta.ToString(), new UTF8Encoding(false));

            Console.WriteLine($"  roads {roadCount}, prefab links {linkCount}, areas {areaCount}, " +
                              $"ferries {ferryCount}, cities {cityCount}");
            Console.WriteLine($"  places {poiCount}  ({string.Join(", ", poiKinds.Select(k => k.Key + " " + k.Value))})");
            if (unknown.Count > 0)
            {
                // Worth seeing rather than swallowing: a DLC or a mod may bring an icon the
                // classifier has no rule for, and this is the only place it would show up.
                Console.WriteLine("  overlays not recognised: " +
                                  string.Join(", ", unknown.OrderByDescending(u => u.Value).Take(12)
                                                           .Select(u => u.Key + " x" + u.Value)) +
                                  (unknown.Count > 12 ? $" (+{unknown.Count - 12} more)" : ""));
            }
            Console.WriteLine($"  {cells.Count} cells, {bytes / 1024 / 1024.0:F1} MB -> {cellDir}");

            if (pngPath != null) RenderOverview(mapper, pngPath, pngSize);

            return 0;
        }

        private static int LaneCount(TsPrefabItem prefab, TsMapPoint point, int index)
        {
            var lanes = point.LaneCount;
            if (lanes == -2 && index < prefab.Prefab.PrefabNodes.Count && point.ControlNodeIndex != -1)
                lanes = prefab.Prefab.PrefabNodes[point.ControlNodeIndex].LaneCount;
            return lanes < 1 ? 1 : lanes;
        }

        /// <summary>A whole-map picture, mostly so the export can be eyeballed for holes.</summary>
        private static void RenderOverview(TsMapper mapper, string path, int size)
        {
            const int padding = 500;
            var renderer = new TsMapRenderer(mapper);
            var palette = new MapPalette
            {
                Background = new SolidBrush(Color.FromArgb(11, 14, 20)),
                Road = new SolidBrush(Color.FromArgb(228, 234, 245)),
                PrefabRoad = new SolidBrush(Color.FromArgb(228, 234, 245)),
                PrefabLight = new SolidBrush(Color.FromArgb(38, 46, 62)),
                PrefabDark = new SolidBrush(Color.FromArgb(52, 62, 82)),
                PrefabGreen = new SolidBrush(Color.FromArgb(34, 54, 44)),
                CityName = new SolidBrush(Color.FromArgb(255, 190, 90)),
                FerryLines = new SolidBrush(Color.FromArgb(90, 120, 170, 255)),
                Error = Brushes.Crimson
            };

            var width = mapper.maxX - mapper.minX + padding * 2;
            var height = mapper.maxZ - mapper.minZ + padding * 2;
            float zoom;
            PointF pos;
            if (width > height)
            {
                zoom = size / width;
                pos = new PointF(mapper.minX - padding, mapper.minZ - padding + -(size / zoom) / 2f + height / 2f);
            }
            else
            {
                zoom = size / height;
                pos = new PointF(mapper.minX - padding + -(size / zoom) / 2f + width / 2f, mapper.minZ - padding);
            }

            Console.Write($"  rendering overview {size}x{size}... ");
            using (var bitmap = new Bitmap(size, size))
            using (var g = Graphics.FromImage(bitmap))
            {
                renderer.Render(g, new Rectangle(0, 0, size, size), zoom, pos, palette,
                    RenderFlags.All & ~RenderFlags.TextOverlay);
                Directory.CreateDirectory(Path.GetDirectoryName(Path.GetFullPath(path)));
                bitmap.Save(path, System.Drawing.Imaging.ImageFormat.Png);
            }
            Console.WriteLine($"{path}");
        }

        private sealed class Cell
        {
            public readonly List<string> Roads = new List<string>();
            public readonly List<string> Areas = new List<string>();
            public readonly List<string> Ferries = new List<string>();
            public readonly List<string> Cities = new List<string>();
            public readonly List<string> Points = new List<string>();

            public string ToJson()
            {
                var sb = new StringBuilder(1024);
                sb.Append("{\"r\":[").Append(string.Join(",", Roads)).Append("]");
                if (Areas.Count > 0) sb.Append(",\"a\":[").Append(string.Join(",", Areas)).Append("]");
                if (Ferries.Count > 0) sb.Append(",\"f\":[").Append(string.Join(",", Ferries)).Append("]");
                if (Cities.Count > 0) sb.Append(",\"c\":[").Append(string.Join(",", Cities)).Append("]");
                if (Points.Count > 0) sb.Append(",\"p\":[").Append(string.Join(",", Points)).Append("]");
                return sb.Append("}").ToString();
            }
        }

        /// <summary>
        /// What kind of place an overlay marks, or null for one the panel has no use for.
        ///
        /// The game's own icon names are the classifier, because they are what the game
        /// draws on its world map -- so anything it shows as a fuel pump is a fuel pump
        /// here too, mods included. Names it has never heard of are dropped rather than
        /// guessed at: an unlabelled dot on a GPS is worse than no dot.
        /// </summary>
        private static string Kind(string type, string name)
        {
            switch (type)
            {
                case "Parking": return "parking";
                case "Garage": return "garage";
                case "TruckDealer": return "dealer";
                case "Recruitment": return "recruit";
                case "Company": return "company";
                case "Ferry":
                case "Train":
                case "BusStop": return null;   // already drawn as lines, or not useful
            }

            var n = (name ?? "").ToLowerInvariant();
            if (n.Contains("gas") || n.Contains("fuel") || n.Contains("petrol")) return "fuel";
            if (n.Contains("service") || n.Contains("repair") || n.Contains("mechanic")) return "service";
            if (n.Contains("weigh") || n.Contains("scale")) return "weigh";
            if (n.Contains("parking") || n.Contains("rest_area") || n.Contains("restarea")) return "parking";
            if (n.Contains("hotel") || n.Contains("motel") || n.Contains("sleep")) return "sleep";
            if (n.Contains("dealer")) return "dealer";
            if (n.Contains("garage")) return "garage";
            if (n.Contains("recruitment")) return "recruit";
            if (n.Contains("viewpoint")) return "viewpoint";
            if (n.Contains("border") || n.Contains("toll")) return "border";
            return null;
        }

        /// <summary>"posped" -> "Posped", "trameri_a" -> "Trameri A". Company tokens are
        /// all the game gives us without its localisation table for them.</summary>
        private static string Pretty(string token)
        {
            if (string.IsNullOrEmpty(token)) return "";
            var parts = token.Replace('.', ' ').Replace('_', ' ').Split(new[] { ' ' },
                                                                       StringSplitOptions.RemoveEmptyEntries);
            for (var i = 0; i < parts.Length; i++)
                parts[i] = char.ToUpperInvariant(parts[i][0]) + parts[i].Substring(1);
            return string.Join(" ", parts);
        }

        /// <summary>A polyline as [width, secret, x, z, x, z, ...] -- flat, because there are millions of these.</summary>
        private static string Encode(List<PointF> points, float width, bool secret)
        {
            var sb = new StringBuilder(16 + points.Count * 12);
            sb.Append('[').Append(N(width)).Append(',').Append(secret ? '1' : '0');
            foreach (var p in points) sb.Append(',').Append(N(p.X)).Append(',').Append(N(p.Y));
            return sb.Append(']').ToString();
        }

        private static string Encode(List<PointF> points)
        {
            var sb = new StringBuilder(points.Count * 12);
            sb.Append('[');
            for (var i = 0; i < points.Count; i++)
            {
                if (i > 0) sb.Append(',');
                sb.Append(N(points[i].X)).Append(',').Append(N(points[i].Y));
            }
            return sb.Append(']').ToString();
        }

        private static string N(float value)
        {
            return Math.Round(value, 1).ToString("0.#", CultureInfo.InvariantCulture);
        }

        private static string Quote(string text)
        {
            var sb = new StringBuilder(text.Length + 2).Append('"');
            foreach (var c in text)
            {
                if (c == '"' || c == '\\') sb.Append('\\').Append(c);
                else if (c < 0x20) sb.Append("\\u").Append(((int)c).ToString("x4"));
                else sb.Append(c);
            }
            return sb.Append('"').ToString();
        }
    }
}
